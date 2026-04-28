from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app import schemas
from app.controller import auth_controller 

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

# --- CUSTOMER REGISTRATION (Mobile App) ---
@router.post("/register/customer", response_model=schemas.UserResponse)
def register_customer(user: schemas.CustomerCreate, db: Session = Depends(get_db)):
    """
    Endpoint for new customer sign-up. 
    Initializes a User account and a linked CustomerProfile.
    """
    return auth_controller.create_customer(db, user)

# --- OWNER REGISTRATION (Admin/Web) ---
@router.post("/register/owner", response_model=schemas.UserResponse)
def register_owner(user: schemas.OwnerCreate, db: Session = Depends(get_db)):
    """
    Endpoint for shop owner registration. 
    Creates the Shop and the Owner account linked to it.
    """
    return auth_controller.create_owner(db, user)

# --- UNIVERSAL LOGIN ---
@router.post("/login", response_model=schemas.LoginResponse)
def login(user_credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    """
    Authenticates both Owners and Customers.
    Returns an access token and the unified user object.
    """
    return auth_controller.authenticate_user(db, user_credentials)

# --- GET USER PROFILE (Dashboard Fetching) ---
@router.get("/profile/{user_id}")
def get_user_profile(user_id: int, db: Session = Depends(get_db)):
    """
    Retrieves user details (First Name, Last Name, Role, etc.) by ID.
    Used for automatic data fetching on the Dashboard and Profile screens.
    """
    return auth_controller.get_current_user_profile(db, user_id)

# --- PROFILE UPDATE (Mobile/Web) ---
@router.put("/profile/update/{user_id}", response_model=schemas.UserResponse)
def update_user_profile(
    user_id: int, 
    profile_data: schemas.UserUpdate, 
    db: Session = Depends(get_db)
):
    """
    Updates personal details in the customer_profiles table.
    Ensures that only users with the 'customer' role are modified.
    """
    updated_user = auth_controller.update_user_profile(db, user_id=user_id, profile_data=profile_data)
    
    if not updated_user:
        raise HTTPException(
            status_code=404, 
            detail="Customer profile not found or user is not a customer"
        )
        
    return updated_user