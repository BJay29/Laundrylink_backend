import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app import models

# --- CONFIG ---
# IMPORTANT: sa production, kunin ito galing sa environment variable
# (.env file), huwag i-hardcode. Panandalian lang ang fallback dito.
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "CHANGE_THIS_IN_PRODUCTION_PLEASE")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours, i-adjust kung gusto mo

bearer_scheme = HTTPBearer()


# =========================================================
# TOKEN CREATION
# =========================================================

def create_access_token(user_id: int, shop_id: Optional[int], role: str) -> str:
    """
    Gumagawa ng totoong signed JWT para sa Shop Owner/Staff (models.User).
    Ang shop_id na naka-embed dito ang magiging SATSATANG PINAGMUMULAN
    ng shop scoping sa buong app — hindi na dapat tanggapin ang shop_id
    galing sa client request (body/query/localStorage).

    "type": "user" — nagsisilbing marker para hindi ito magamit
    sa customer-only endpoints, kahit valid ang signature.
    """
    payload = {
        "sub": str(user_id),
        "shop_id": shop_id,
        "role": role,
        "type": "user",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_customer_access_token(customer_id: int) -> str:
    """
    Gumagawa ng totoong signed JWT para sa Customer (models.Customer, mobile app).
    Walang shop_id/role dito dahil hindi naka-tie ang isang customer
    sa iisang shop lang — pwede silang mag-book sa ibat-ibang shops.

    "type": "customer" — nagsisilbing marker para hindi ito magamit
    sa staff/owner-only endpoints, kahit valid ang signature.
    """
    payload = {
        "sub": str(customer_id),
        "type": "customer",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired, please log in again",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )


# =========================================================
# DEPENDENCIES — SHOP OWNER / STAFF (models.User)
# =========================================================

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    """
    Dependency na ilalagay sa BAWAT protected route na para lang
    sa Shop Owner/Staff (booking, machine, inventory, analytics, settings).
    Kinukuha ang user mula sa JWT — hindi galing sa request body/query.

    Gamit:
        current_user: models.User = Depends(get_current_user)
        ...
        db.query(Model).filter(Model.shop_id == current_user.shop_id)

    Tinatanggihan ang customer tokens kahit valid ang signature —
    dahil ibang "type" ang laman ng payload nila.
    """
    payload = decode_access_token(credentials.credentials)

    if payload.get("type") != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is not accessible with a customer account",
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


def require_role(*allowed_roles: str):
    """
    Optional na dependency factory para sa role-based restrictions.
    Gamit: Depends(require_role("owner"))
    """
    def role_checker(current_user: models.User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission to perform this action",
            )
        return current_user
    return role_checker


# =========================================================
# DEPENDENCIES — CUSTOMER (models.Customer, mobile app)
# =========================================================

def get_current_customer(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.Customer:
    """
    Dependency na ilalagay sa BAWAT protected route na para lang
    sa Customer (mobile app booking, profile, order history, atbp.).
    Kinukuha ang customer mula sa JWT — hindi galing sa request body/query.

    Gamit:
        current_customer: models.Customer = Depends(get_current_customer)

    Tinatanggihan ang staff/owner tokens kahit valid ang signature —
    dahil ibang "type" ang laman ng payload nila.
    """
    payload = decode_access_token(credentials.credentials)

    if payload.get("type") != "customer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only accessible with a customer account",
        )

    customer_id = payload.get("sub")
    if customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    customer = db.query(models.Customer).filter(models.Customer.id == int(customer_id)).first()
    if customer is None or not customer.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Customer not found or inactive",
        )

    if not customer.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account not verified",
        )

    return customer