from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app import schemas, models
from app.controller import auth_controller
from app.security import get_current_user  # ⬅️ BAGONG IMPORT

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

# --- BACKEND-ONLY REGISTRATION (Hidden from UI) ---
@router.post("/register/owner", response_model=schemas.UserResponse)
def register_owner(user: schemas.OwnerCreate, db: Session = Depends(get_db)):
    """
    Endpoint for creating shop owner accounts via Thunder Client.
    This is used to populate the database without needing a frontend registration form.
    """
    return auth_controller.create_owner(db, user)


# --- UNIVERSAL LOGIN (Web & Mobile) ---
@router.post("/login", response_model=schemas.LoginResponse)
def login(user_credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    """
    Primary authentication endpoint for both React (Web) and Flutter (Mobile).
    Validates credentials and returns a REAL JWT + shop context (ID, Name, Address).
    """
    return auth_controller.authenticate_user(db, user_credentials)


# --- SESSION DATA FETCHING (PROTECTED, SELF ONLY) ---
@router.get("/profile", response_model=schemas.UserResponse)
def get_my_profile(current_user: models.User = Depends(get_current_user)):
    """
    Retrieves session details of the CURRENTLY LOGGED-IN user only,
    based on the JWT sent in the Authorization header.

    Dating "/profile/{user_id}" ay pwedeng ma-access ng kahit sino
    basta may alam na user ID (1, 2, 3...) — walang authentication check.
    Ngayon, base na sa verified JWT ang result, kaya imposibleng
    makita ng isang user ang profile/shop data ng iba.
    """
    return {
        "email": current_user.email,
        "role": current_user.role,
        "shop_id": current_user.shop_id,
        "shop_name": getattr(current_user.shop, 'shop_name', None) if current_user.shop else None,
        "address": getattr(current_user.shop, 'address', None) if current_user.shop else None,
    }