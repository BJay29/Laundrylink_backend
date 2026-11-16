import os
import json
import urllib.request
import urllib.error
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app import models, schemas
from app.services import weather_service


def register_shop_for_owner(db: Session, shop_data: schemas.OwnerCreate, current_user: models.User):
    """
    UPDATED (Supabase Auth migration): pinalitan ang dating create_owner().

    Bagong flow: sa Supabase Auth na nangyayari ang account creation
    (signUp + OTP verify), tapos ang webhook (webhook_controller.
    sync_verified_user) na ang gumagawa ng User row sa Aiven DB —
    pero WALANG shop_id pa noon, dahil hindi pa alam ng webhook kung
    anong shop ang gagawin ng owner na ito.

    Ito ang TUMUTUPAD sa "gumawa ng shop" na parte: tinatawag ito ng
    frontend PAGKATAPOS mag-login gamit ang Supabase JWT (kaya may
    current_user na, na-resolve na via get_current_user dependency).
    Ginagawa dito ang Shop entity, tapos ni-link ang current_user
    (na naka-synced na mula sa webhook) papunta rito.

    UPDATED (weather forecast fix): ang bagong Shop ay may default na
    coordinates na ng Naga City, Camarines Sur (galing sa
    weather_service.DEFAULT_LATITUDE/DEFAULT_LONGITUDE), para hindi na
    NULL ang latitude/longitude at gumana agad ang weather forecast.
    Pwede itong palitan ng owner mamaya sa shop profile settings
    (PUT /settings/profile — tumatanggap na ng latitude/longitude).
    """
    # Owner lang dapat ang tumatawag dito, at isang beses lang dapat
    # (hindi na dapat may existing shop_id na).
    if current_user.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owner accounts can register a shop."
        )

    if current_user.shop_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account is already linked to a shop."
        )

    shop_name = (shop_data.shop_name or "").strip()
    name_taken_error = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Shop name already taken. Please choose a different name.",
    )

    # Friendly pre-check (hindi case-sensitive). Ang unique constraint sa DB
    # (shops_shop_name_key) ang huling proteksyon kapag sabay ang dalawang request.
    existing_shop = (
        db.query(models.Shop)
        .filter(func.lower(models.Shop.shop_name) == shop_name.lower())
        .first()
    )
    if existing_shop:
        raise name_taken_error

    new_shop = models.Shop(
        shop_name=shop_name,
        address=shop_data.address,
        latitude=weather_service.DEFAULT_LATITUDE,
        longitude=weather_service.DEFAULT_LONGITUDE,
    )
    try:
        db.add(new_shop)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise name_taken_error
    db.refresh(new_shop)

    current_user.shop_id = new_shop.id
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    # Attach shop details for the response (parehong pattern ng dati).
    current_user.shop_name = new_shop.shop_name
    current_user.address = new_shop.address

    return current_user


def _create_supabase_user(email: str, password: str, full_name: str, role: str) -> str:
    """
    Gumagawa ng TUNAY na Supabase Auth account gamit ang Admin API
    (service role key), naka-verify na agad ang email (email_confirm=True)
    kaya HINDI na kailangan ng OTP at agad nang makaka-login ang staff.

    Kailangan ng dalawang env var sa Render:
      SUPABASE_URL                (hal. https://xxxx.supabase.co)
      SUPABASE_SERVICE_ROLE_KEY   (Settings > API > service_role — SECRET,
                                   huwag ilagay sa frontend)

    Nagbabalik ng supabase user id (uuid).
    """
    base = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not base or not key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server is missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY."
        )

    body = json.dumps({
        "email": email,
        "password": password,
        "email_confirm": True,
        "user_metadata": {"full_name": full_name, "role": role},
    }).encode()
    req = urllib.request.Request(
        f"{base}/auth/v1/admin/users",
        data=body,
        method="POST",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())["id"]
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("msg") or ""
        except Exception:
            msg = ""
        if e.code in (409, 422) and ("registered" in msg.lower() or "exists" in msg.lower()):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=msg or "Could not create the login account."
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the authentication service. Please try again."
        )


def create_staff(db: Session, staff_data: schemas.StaffCreate, shop_id: int):
    """
    UPDATED: dati placeholder row lang ito (walang Supabase account),
    kaya hindi makapag-login ang staff — kailangan pa nilang mag-sign-up
    at mag-OTP. Ngayon, gumagawa na ng tunay na Supabase Auth account
    (naka-verify na ang email) AT ng User row na naka-link na agad
    (supabase_uid), kaya makaka-login ang staff/manager/rider agad gamit
    ang email at temporary password.

    Roles: "staff", "manager", "rider" (validated sa schemas.py).
    """
    email = staff_data.email.strip().lower()

    existing = db.query(models.User).filter(func.lower(models.User.email) == email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    supabase_uid = _create_supabase_user(
        email, staff_data.password, staff_data.full_name, staff_data.role
    )

    # Maaaring nauna nang gumawa ng row ang Supabase webhook (walang
    # shop/role pa) — i-update na lang iyon sa halip na gumawa ng duplicate.
    user = db.query(models.User).filter(models.User.supabase_uid == supabase_uid).first()
    if user is None:
        user = db.query(models.User).filter(func.lower(models.User.email) == email).first()

    if user is None:
        user = models.User(email=email)
        db.add(user)

    user.role = staff_data.role
    user.full_name = staff_data.full_name
    user.shop_id = shop_id
    user.supabase_uid = supabase_uid
    user.is_active = True

    try:
        db.commit()
    except IntegrityError:
        # Maaaring naunahan tayo ng Supabase webhook sa paggawa ng row —
        # i-update na lang ang row na iyon.
        db.rollback()
        user = db.query(models.User).filter(func.lower(models.User.email) == email).first()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        user.role = staff_data.role
        user.full_name = staff_data.full_name
        user.shop_id = shop_id
        user.supabase_uid = supabase_uid
        user.is_active = True
        db.commit()
    db.refresh(user)
    return user


TEAM_ROLES = ("staff", "manager", "rider")


def list_staff(db: Session, shop_id: int):
    """Lahat ng staff/manager/rider ng shop (hindi kasama ang owner)."""
    return (
        db.query(models.User)
        .filter(
            models.User.shop_id == shop_id,
            models.User.role.in_(TEAM_ROLES),
            models.User.is_active == True,
        )
        .order_by(models.User.created_at.desc())
        .all()
    )


def _delete_supabase_user(supabase_uid: str) -> None:
    """Binubura ang login account sa Supabase para hindi na makapag-login."""
    base = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not base or not key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server is missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY."
        )
    req = urllib.request.Request(
        f"{base}/auth/v1/admin/users/{supabase_uid}",
        method="DELETE",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
    )
    try:
        urllib.request.urlopen(req, timeout=15).close()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return  # wala na pala sa Supabase — OK lang
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not remove the login account. Please try again."
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the authentication service. Please try again."
        )


def delete_staff(db: Session, user_id: int, current_user: models.User):
    """
    Owner-only: binubura ang staff/manager/rider ng sarili niyang shop.
    Binubura ang Supabase login at ang User row. Kung may mga record na
    nakakabit pa sa user (FK), dini-deactivate na lang at nire-rename ang
    email para magamit ulit ng iba.
    """
    target = (
        db.query(models.User)
        .filter(models.User.id == user_id, models.User.shop_id == current_user.shop_id)
        .first()
    )
    if not target or target.role not in TEAM_ROLES:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team member not found.")
    if target.id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account.")

    name = target.full_name or target.email

    if target.supabase_uid:
        _delete_supabase_user(target.supabase_uid)

    try:
        db.delete(target)
        db.commit()
    except IntegrityError:
        db.rollback()
        target = db.query(models.User).filter(models.User.id == user_id).first()
        target.is_active = False
        target.supabase_uid = None
        target.email = f"deleted-{target.id}-{target.email}"
        db.commit()

    return {"message": f"{name} was removed."}




# REMOVED: authenticate_user() — hindi na FastAPI ang humahawak ng
# login/password verification, ang Supabase Auth SDK na
# (signInWithPassword) sa frontend mismo ang gumagawa nito at
# direktang nagbibigay ng JWT doon.
#
# REMOVED: get_current_user_profile() — dati pa itong tinanggal noon,
# pinalitan ng get_current_user() dependency sa security.py.