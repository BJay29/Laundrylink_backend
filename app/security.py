import os

import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app import models

# --- CONFIG ---
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_JWKS_URL = f"{SUPABASE_URL}/auth/v1/jwks"

# NEW — kailangan pala ng 'apikey' header ang mismong pag-fetch sa
# JWKS endpoint (quirk ng Supabase's API gateway/Kong — kahit "public"
# dapat itong endpoint, kailangan pa rin nitong makapasa sa gateway
# gamit ang isang valid apikey, kahit hindi naman talaga "authenticated"
# na request). Ito ang naging sanhi ng
# "PyJWKClientConnectionError: HTTP Error 401" — walang apikey header
# na naipapadala dati.
#
# NEW — kailangan mo idagdag itong env var sa Render:
#   SUPABASE_ANON_KEY = <yung publishableKey/anonKey mo mismo sa
#   main.dart's Supabase.initialize() call>
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]

_jwks_client = PyJWKClient(
    SUPABASE_JWKS_URL,
    headers={"apikey": SUPABASE_ANON_KEY},
)

bearer_scheme = HTTPBearer()


# =========================================================
# TOKEN VERIFICATION (Supabase-issued tokens, ES256/asymmetric)
# =========================================================

def decode_supabase_token(token: str) -> dict:
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
    return current_user.shop_id


def require_role(*allowed_roles: str):
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