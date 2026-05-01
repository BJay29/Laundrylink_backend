from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app import schemas
from app.controller import auth_controller 

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
    Validates credentials and returns the shop context (ID, Name, and Address).
    """
    return auth_controller.authenticate_user(db, user_credentials)

# --- SESSION DATA FETCHING ---
@router.get("/profile/{user_id}", response_model=schemas.UserResponse)
def get_user_session_data(user_id: int, db: Session = Depends(get_db)):
    """
    Retrieves essential session details by User ID.
    Used to persist shop information on the Dashboard after a successful login.
    """
    user_data = auth_controller.get_current_user_profile(db, user_id)
    
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="User session data not found"
        )
        
    return user_data