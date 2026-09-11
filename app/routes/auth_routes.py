from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.database import get_db
from app import schemas, models
from app.controller import auth_controller
from app.security import get_current_user, require_role

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


# --- SHOP REGISTRATION (kailangan nang naka-login via Supabase) ---
@router.post("/register-shop", response_model=schemas.UserResponse)
def register_shop(
    shop_data: schemas.OwnerCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    UPDATED (Supabase Auth migration): pinalitan ang dating
    POST /auth/register/owner.

    BAGONG FLOW: hindi na ito ang gumagawa ng account — nangyari na
    ang account creation sa Supabase Auth (signUp + OTP verify),
    at nag-sync na ang User row (walang shop_id pa) papunta sa Aiven
    DB via webhook BAGO pa man ma-tawag ang endpoint na ito. Kaya
    PROTECTED na endpoint na ito (may Depends(get_current_user)) —
    tinatawag ito ng frontend PAGKATAPOS mag-login (may valid Supabase
    JWT na), para lang kumpletuhin ang "gumawa ng shop" na hakbang.
    """
    return auth_controller.register_shop_for_owner(db, shop_data, current_user)


# --- STAFF/MANAGER INVITATION (Owner-only) ---
@router.post("/register/staff", response_model=schemas.StaffResponse, status_code=status.HTTP_201_CREATED)
def register_staff(
    staff_data: schemas.StaffCreate,
    current_user: models.User = Depends(require_role("owner")),
    db: Session = Depends(get_db)
):
    """
    Gumagawa ng "invitation" record para sa bagong staff/manager UNDER
    THE LOGGED-IN OWNER'S OWN SHOP. Hindi pa ito kumpletong account —
    kailangan pang mag-sign-up mismo ang staff member sa Supabase Auth
    gamit ang PAREHONG email para makumpleto ang kanilang access
    (see auth_controller.create_staff docstring).
    """
    return auth_controller.create_staff(db, staff_data, shop_id=current_user.shop_id)


# --- SESSION DATA FETCHING (PROTECTED, SELF ONLY) ---
@router.get("/profile", response_model=schemas.UserResponse)
def get_my_profile(current_user: models.User = Depends(get_current_user)):
    """
    Retrieves session details of the CURRENTLY LOGGED-IN user only,
    based on the Supabase JWT sent in the Authorization header.
    Walang binago dito — parehong gumagana ito kasama ng bagong
    get_current_user() sa security.py.
    """
    return {
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "shop_id": current_user.shop_id,
        "shop_name": getattr(current_user.shop, 'shop_name', None) if current_user.shop else None,
        "address": getattr(current_user.shop, 'address', None) if current_user.shop else None,
    }


# REMOVED: POST /auth/login — hindi na FastAPI ang nagbibigay ng JWT.
# Sa frontend, gagamitin na lang ang Supabase Auth SDK mismo:
#   supabase.auth.signInWithPassword({ email, password })
# at ang ibinabalik na session.access_token ang ipapasa bilang
# "Authorization: Bearer <token>" papunta sa lahat ng protected
# FastAPI endpoints (kasama na ang /auth/profile at /auth/register-shop
# sa itaas).