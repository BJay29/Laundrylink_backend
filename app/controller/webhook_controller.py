from sqlalchemy.orm import Session

from app import models


def sync_verified_user(db: Session, supabase_uid: str, email: str, role: str, metadata: dict) -> dict:
    """
    Tinatanggap ang verified na Supabase user data (galing sa webhook
    payload, matapos ma-verify ang email/OTP) at ini-upsert papunta sa
    tamang local table (User o Customer) base sa role.

    Idempotent ito — puwedeng tumawag nang paulit-ulit (retries ng
    Supabase kung sakaling nag-timeout o nagkaroon ng error) nang walang
    duplicate rows, dahil naghahanap muna tayo via email bago gumawa ng
    bago.

    Params:
        db: aktibong DB session (galing sa Depends(get_db))
        supabase_uid: ang record.id mula sa webhook payload (UUID string)
        email: ang record.email mula sa webhook payload
        role: galing sa raw_user_meta_data.role ("customer", "owner",
              o "staff") — ito ang nagsasabi kung saang table dapat
              i-sync ang user na ito
        metadata: buong raw_user_meta_data dict, pinagkukunan ng
                  full_name, mobile_number, atbp.

    Returns:
        dict na may "table" (alin sa "customers"/"users") at "id"
        (local integer id) ng na-sync na record — ginagamit lang para
        sa webhook response/logging, hindi kritikal sa logic.
    """
    if role == "customer":
        return _sync_customer(db, supabase_uid, email, metadata)

    # "owner" o "staff" — parehong napupunta sa User table
    return _sync_user(db, supabase_uid, email, role, metadata)


def _sync_customer(db: Session, supabase_uid: str, email: str, metadata: dict) -> dict:
    """Upsert logic para sa models.Customer (mobile app users)."""
    customer = db.query(models.Customer).filter(models.Customer.email == email).first()

    if customer:
        # Existing na customer record (hal. dating na-seed, o paulit-ulit
        # na webhook call) — i-update lang ang supabase_uid at
        # is_verified, wag galawin ang ibang fields nila.
        customer.supabase_uid = supabase_uid
        customer.is_verified = True
    else:
        customer = models.Customer(
            email=email,
            supabase_uid=supabase_uid,
            is_verified=True,
            full_name=metadata.get("full_name", ""),
            mobile_number=metadata.get("mobile_number", ""),
        )
        db.add(customer)

    db.commit()
    db.refresh(customer)

    return {"table": "customers", "id": customer.id}


def _sync_user(db: Session, supabase_uid: str, email: str, role: str, metadata: dict) -> dict:
    """Upsert logic para sa models.User (shop Owner/Staff, web app)."""
    user = db.query(models.User).filter(models.User.email == email).first()

    if user:
        user.supabase_uid = supabase_uid
        # NOTE: hindi natin ino-overwrite ang role/shop_id dito kung
        # meron nang existing user — baka sinadyang na-configure na ito
        # ng ibang admin flow (hal. StaffCreate endpoint). Ang webhook
        # ay basta nagpapatunay lang na "verified na ang Supabase
        # identity na ito", hindi awtoridad sa role assignment.
    else:
        user = models.User(
            email=email,
            supabase_uid=supabase_uid,
            role=role,
            full_name=metadata.get("full_name", ""),
        )
        db.add(user)

    db.commit()
    db.refresh(user)

    return {"table": "users", "id": user.id}