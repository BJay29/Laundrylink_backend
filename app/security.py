import os

import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app import models

# --- CONFIG ---
# UPDATED: ang project mo pala ay gumagamit na ng bagong ASYMMETRIC JWT
# Signing Keys (ES256), hindi na Legacy HS256 secret (kumpirmado via
# InvalidAlgorithmError sa Render logs — "alg": "ES256" ang laman ng
# token header). Kaya hindi na natin magagamit ang isang static
# SUPABASE_JWT_SECRET para i-verify — kailangan nating kumuha ng PUBLIC
# KEY mula sa Supabase's JWKS endpoint (auto-discovered, cached, at
# awtomatikong nire-refresh ni PyJWKClient base sa 'kid' na nasa header
# ng bawat token).
#
# NEW — kailangan mo idagdag itong env var sa Render:
#   SUPABASE_URL = https://<project-ref>.supabase.co
# (parehong URL na ginamit mo sa Supabase.initialize() sa main.dart mo)
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_JWKS_URL = f"{SUPABASE_URL}/auth/v1/jwks"

# PyJWKClient — kino-cache nito ang mga public keys at awtomatikong
# nire-refresh/nire-fetch ulit kapag may bagong 'kid' na hindi pa
# nakikilala (hal. pagkatapos ng key rotation sa Supabase side).
_jwks_client = PyJWKClient(SUPABASE_JWKS_URL)

bearer_scheme = HTTPBearer()


# =========================================================
# TOKEN VERIFICATION (Supabase-issued tokens, ES256/asymmetric)
# =========================================================

def decode_supabase_token(token: str) -> dict:
    """
    Ini-verify ang signature ng isang Supabase-issued JWT (ES256,
    asymmetric) gamit ang public key na kinuha mula sa project's JWKS
    endpoint, at ibinabalik ang laman nito. 'sub' claim dito ang
    Supabase auth.users.id (UUID string) — ito ang gagamitin nating
    hanapin sa local User/Customer table via supabase_uid column.
    """
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again.",
        )
    except jwt.InvalidTokenError as e:
        print(f"DEBUG: JWT decode failed — {type(e).__name__}: {e}")
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
    """Convenience dependency na direktang nagbabalik ng shop_id (int)."""
    return current_user.shop_id


def require_role(*allowed_roles: str):
    """Optional na dependency factory para sa role-based restrictions."""
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