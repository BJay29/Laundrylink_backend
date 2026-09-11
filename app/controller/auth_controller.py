from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app import models, schemas


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

    new_shop = models.Shop(
        shop_name=shop_data.shop_name,
        address=shop_data.address
    )
    db.add(new_shop)
    db.commit()
    db.refresh(new_shop)

    current_user.shop_id = new_shop.id
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    # Attach shop details for the response (parehong pattern ng dati).
    current_user.shop_name = new_shop.shop_name
    current_user.address = new_shop.address

    return current_user


def create_staff(db: Session, staff_data: schemas.StaffCreate, shop_id: int):
    """
    UPDATED (Supabase Auth migration): gumagawa na lang ng "placeholder"
    User row (walang password, walang supabase_uid pa) sa halip na
    kumpletong account. Ito ay isang "invitation" — kapag nag-sign-up
    ang bagong staff member gamit ang PAREHONG email sa Supabase Auth
    (at na-verify nila ang OTP), ang webhook_controller._sync_user()
    ay makikita ang email match na ito at ang gagawin na lang niya ay
    i-set ang supabase_uid dito (hindi na gagawa ng bagong duplicate
    row) — see webhook_controller.py.

    Ang Owner ang responsable na sabihan ang staff member (offline,
    hal. via email/chat) kung anong email ang ginamit dito, para
    magkatugma sila pag-sign-up ng staff sa Supabase.
    """
    existing = db.query(models.User).filter(models.User.email == staff_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    new_staff = models.User(
        email=staff_data.email,
        role=staff_data.role,   # "staff" or "manager" — validated in schemas.py
        full_name=staff_data.full_name,
        shop_id=shop_id,
        supabase_uid=None,      # kakabit pa lang, hihintayin ang webhook sync
    )
    db.add(new_staff)
    db.commit()
    db.refresh(new_staff)

    return new_staff


# REMOVED: authenticate_user() — hindi na FastAPI ang humahawak ng
# login/password verification, ang Supabase Auth SDK na
# (signInWithPassword) sa frontend mismo ang gumagawa nito at
# direktang nagbibigay ng JWT doon.
#
# REMOVED: get_current_user_profile() — dati pa itong tinanggal noon,
# pinalitan ng get_current_user() dependency sa security.py.