from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app import schemas, models
from app.controller import auth_controller
from app.security import get_current_user, require_role

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

# --- BACKEND-ONLY REGISTRATION (Hidden from UI) ---
@router.post("/register/owner", response_model=schemas.UserResponse)
def register_owner(user: schemas.OwnerCreate, db: Session = Depends(get_db)):
    """
    Endpoint for creating shop owner accounts.
    Public — anyone can register a new shop, since a Shop + its first
    Owner account are created together.
    """
    return auth_controller.create_owner(db, user)


# --- STAFF/MANAGER REGISTRATION (Owner-only) ---
@router.post("/register/staff", response_model=schemas.StaffResponse, status_code=status.HTTP_201_CREATED)
def register_staff(
    staff_data: schemas.StaffCreate,
    current_user: models.User = Depends(require_role("owner")),
    db: Session = Depends(get_db)
):
    """
    Creates a new staff/manager account UNDER THE LOGGED-IN OWNER'S OWN SHOP.

    Unlike /register/owner, this does NOT create a new Shop — it links the
    new account to current_user.shop_id, so it's always the Owner's own
    shop, never a shop_id supplied by the client. Restricted to
    role="owner" via require_role() — a staff or manager account cannot
    create other staff accounts.

    This is what the frontend's "Add Staff" button (inside the dashboard,
    NOT the public Sign Up page) calls. The new staff member then logs in
    normally via the SAME /auth/login endpoint everyone else uses — no
    separate staff login flow exists.
    """
    return auth_controller.create_staff(db, staff_data, shop_id=current_user.shop_id)


# --- UNIVERSAL LOGIN (Web & Mobile) ---
@router.post("/login", response_model=schemas.LoginResponse)
def login(user_credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    """
    Primary authentication endpoint for both React (Web) and Flutter (Mobile).
    Validates credentials and returns a REAL JWT + shop context (ID, Name, Address).

    Used by EVERYONE — Owner, Staff, and Manager accounts alike. The role
    embedded in the resulting JWT is determined entirely by which User row
    matches the given email (set once at account creation time), not by
    anything this endpoint decides.
    """
    return auth_controller.authenticate_user(db, user_credentials)


# --- SESSION DATA FETCHING (PROTECTED, SELF ONLY) ---
@router.get("/profile", response_model=schemas.UserResponse)
def get_my_profile(current_user: models.User = Depends(get_current_user)):
    """
    Retrieves session details of the CURRENTLY LOGGED-IN user only,
    based on the JWT sent in the Authorization header.

    Previously "/profile/{user_id}" was accessible by anyone who knew a
    valid user ID (1, 2, 3...) — no authentication check. Now it's based
    on the verified JWT, so it's impossible for one user to see another
    user's profile/shop data.
    """
    return {
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "shop_id": current_user.shop_id,
        "shop_name": getattr(current_user.shop, 'shop_name', None) if current_user.shop else None,
        "address": getattr(current_user.shop, 'address', None) if current_user.shop else None,
    }