import os
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app import models

# --- CONFIG ---
# UPDATED (Supabase Auth migration): hindi na natin sariling SECRET_KEY
# ang ginagamit para mag-verify ng tokens — ang Supabase Auth na ang
# gumagawa/nag-sign ng access tokens (sa React/Flutter side, via
# signInWithPassword()). Ang FastAPI ay isa na lang na "consumer" ng
# mga tokens na iyon — dito lang natin kailangan ang
# SUPABASE_JWT_SECRET para i-verify ang signature. Makikita ito sa
# Supabase Dashboard → Project Settings → API → JWT Keys →
# "Legacy JWT Secret" → Reveal.
SUPABASE_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]
ALGORITHM = "HS256"

bearer_scheme = HTTPBearer()


# =========================================================
# TOKEN VERIFICATION (Supabase-issued tokens)
# =========================================================

def decode_supabase_token(token: str) -> dict:
    """
    Ini-verify ang signature ng isang Supabase-issued JWT at ibinabalik
    ang laman nito. 'sub' claim dito ang Supabase auth.users.id (UUID
    string) — ito ang gagamitin nating hanapin sa local User/Customer
    table via supabase_uid column (see models.py).
    """
    try:
        return jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=[ALGORITHM],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        print("DEBUG: JWT decode failed — token expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )
    except jwt.InvalidTokenError as e:
        # TEMPORARY DEBUG LOGGING — para makita natin sa Render logs
        # ang TUNAY na dahilan ng 401 (mali bang secret/algorithm,
        # invalid signature, wrong audience, atbp.) sa halip na ang
        # generic message lang na nakikita ng client. Tatanggalin na
        # lang ito once na-solve na ang root cause.
        print(f"DEBUG: JWT decode failed — {type(e).__name__}: {e}")
        print(f"DEBUG: token header (first 40 chars): {token[:40]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
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
    """
    claims = decode_supabase_token(credentials.credentials)
    supabase_uid = claims.get("sub")

    if supabase_uid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    user = db.query(models.User).filter(models.User.supabase_uid == supabase_uid).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found, inactive, or not yet synced. Please try again in a moment.",
        )

    return user


def get_current_shop_id(current_user: models.User = Depends(get_current_user)) -> int:
    """
    Convenience dependency na direktang nagbabalik ng shop_id (int)
    imbes na buong User object.
    """
    return current_user.shop_id


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
    """
    claims = decode_supabase_token(credentials.credentials)
    supabase_uid = claims.get("sub")

    if supabase_uid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    customer = db.query(models.Customer).filter(models.Customer.supabase_uid == supabase_uid).first()
    if customer is None or not customer.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Customer not found, inactive, or not yet synced. Please try again in a moment.",
        )

    return customer