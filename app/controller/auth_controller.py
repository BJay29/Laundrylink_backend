import bcrypt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app import models, schemas
from app.security import create_access_token  # ⬅️ BAGONG IMPORT


def create_owner(db: Session, user: schemas.OwnerCreate):
    """
    Backend-only registration for Shop Owners.
    Creates a new shop entity and links the owner account to it.
    Used for populating the database via Thunder Client.
    """
    # 1. Check if the email is already in use
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # 2. Create the Shop entity first
    new_shop = models.Shop(
        shop_name=user.shop_name,
        address=user.address
    )
    db.add(new_shop)
    db.commit()
    db.refresh(new_shop)

    # 3. Create the Owner account linked to the new shop
    hashed_pass = bcrypt.hashpw(
        user.password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')

    new_user = models.User(
        email=user.email,
        hashed_password=hashed_pass,
        role="owner",
        shop_id=new_shop.id
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # 4. Attach shop details for the response
    new_user.shop_name = new_shop.shop_name
    new_user.address = new_shop.address

    return new_user


def create_staff(db: Session, staff_data: schemas.StaffCreate, shop_id: int):
    """
    NEW — Creates a new staff/manager account UNDER AN EXISTING shop.

    Unlike create_owner(), this does NOT create a new Shop — it links the
    new User directly to shop_id, which is always supplied by the caller
    (the auth_routes.py endpoint), never trusted from client input. The
    caller is responsible for ensuring shop_id comes from the currently
    logged-in Owner's own JWT (via require_role("owner")), so a staff
    account can only ever be created under the Owner's own shop.

    This is what enables individual login accounts per staff/manager,
    which in turn is what makes the Activity Log meaningful — each
    action gets attributed to the real person who performed it instead
    of a generic shared account.
    """
    # 1. Check if the email is already in use
    existing = db.query(models.User).filter(models.User.email == staff_data.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # 2. Hash the password
    hashed_pass = bcrypt.hashpw(
        staff_data.password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')

    # 3. Create the staff/manager account linked to the Owner's own shop
    new_staff = models.User(
        email=staff_data.email,
        hashed_password=hashed_pass,
        role=staff_data.role,   # "staff" or "manager" — validated in schemas.py
        shop_id=shop_id
    )
    db.add(new_staff)
    db.commit()
    db.refresh(new_staff)

    return new_staff


def authenticate_user(db: Session, credentials: schemas.UserLogin):
    """
    Authenticates administrative users (Owners/Staff/Managers) via email
    and password. Returns a unified payload with a REAL signed JWT for
    both React and Flutter.

    NOTE: this function is UNCHANGED by the addition of staff accounts —
    it looks up whichever User row matches the given email, and that
    row's own `role` and `shop_id` (set once, at account creation time,
    either in create_owner() or create_staff()) are what get embedded
    in the JWT. There is no separate "staff login" path; the same
    lookup-by-email logic naturally returns the correct role for
    whoever is logging in.
    """

    # 1. Fetch user by email
    user = db.query(models.User).filter(
        models.User.email == credentials.email
    ).first()

    # 2. Verify existence and password
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid email or password"
        )

    if not bcrypt.checkpw(
        credentials.password.encode('utf-8'),
        user.hashed_password.encode('utf-8')
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid email or password"
        )

    # 3. Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Contact your administrator."
        )

    # 4. Build response payload
    user_payload = {
        "email": user.email,
        "role": user.role,
        "shop_id": user.shop_id,
        "shop_name": getattr(user.shop, 'shop_name', None) if user.shop else None,
        "address": getattr(user.shop, 'address', None) if user.shop else None,
    }

    # 5. Generate a REAL signed JWT — shop_id at role naka-embed na dito.
    #    Ito na ang magiging pinagmumulan ng shop scoping sa buong app,
    #    hindi na yung shop_id na ipinapasa ng client.
    token = create_access_token(
        user_id=user.id,
        shop_id=user.shop_id,
        role=user.role
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_payload
    }


# NOTE: Tinanggal na ang get_current_user_profile(db, user_id) dito.
# Pinalitan ito ng get_current_user() dependency sa security.py,
# na kumukuha na base sa JWT — hindi na sa pamamagitan ng arbitrary
# user_id sa URL (dating security hole: kahit sinong user_id, makikita).