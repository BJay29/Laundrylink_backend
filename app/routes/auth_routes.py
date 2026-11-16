from fastapi import APIRouter, Depends, status
from typing import List
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


# --- STAFF / MANAGER / RIDER ACCOUNTS (Owner-only) ---
@router.post("/register/staff", response_model=schemas.StaffResponse, status_code=status.HTTP_201_CREATED)
def register_staff(
    staff_data: schemas.StaffCreate,
    current_user: models.User = Depends(require_role("owner")),
    db: Session = Depends(get_db)
):
    """
    UPDATED: gumagawa na ng TUNAY na Supabase login account (naka-verify
    na ang email, walang OTP) at User row sa shop ng owner. Roles:
    staff, manager, rider. Makaka-login agad ang bagong account gamit
    ang email at temporary password.
    """
    return auth_controller.create_staff(db, staff_data, shop_id=current_user.shop_id)


@router.get("/staff", response_model=List[schemas.StaffResponse])
def list_staff(
    current_user: models.User = Depends(require_role("owner")),
    db: Session = Depends(get_db)
):
    """NEW: listahan ng staff/manager/rider ng shop ng owner."""
    return auth_controller.list_staff(db, current_user.shop_id)


@router.delete("/staff/{user_id}")
def delete_staff(
    user_id: int,
    current_user: models.User = Depends(require_role("owner")),
    db: Session = Depends(get_db)
):
    """NEW: binubura ng owner ang isang team member (Supabase login + row)."""
    return auth_controller.delete_staff(db, user_id, current_user)


# --- SESSION DATA FETCHING (PROTECTED, SELF ONLY) ---
@router.get("/profile", response_model=schemas.UserResponse)
def get_my_profile(current_user: models.User = Depends(get_current_user)):
    """
    Retrieves session details of the CURRENTLY LOGGED-IN user only,
    based on the Supabase JWT sent in the Authorization header.
    """
    return {
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "shop_id": current_user.shop_id,
        "shop_name": getattr(current_user.shop, 'shop_name', None) if current_user.shop else None,
        "address": getattr(current_user.shop, 'address', None) if current_user.shop else None,
    }


# REMOVED: POST /auth/login — Supabase Auth SDK na ang humahawak ng login
# (supabase.auth.signInWithPassword) sa frontend.