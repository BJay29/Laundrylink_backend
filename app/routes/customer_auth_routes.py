from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app import schemas
from app.controller import customer_auth_controller

router = APIRouter(
    prefix="/customer",
    tags=["Customer Authentication"]
)

# --- CUSTOMER REGISTRATION (Mobile App) ---
@router.post("/register", response_model=schemas.CustomerResponse)
def register_customer(customer: schemas.CustomerCreate, db: Session = Depends(get_db)):
    """
    Endpoint for customer self-registration via the Flutter mobile app.
    Creates a new customer account not tied to any specific shop.
    """
    return customer_auth_controller.register_customer(db, customer)

# --- CUSTOMER LOGIN (Mobile App) ---
@router.post("/login")
def login(credentials: schemas.CustomerLogin, db: Session = Depends(get_db)):
    """
    Authentication endpoint for the Flutter mobile app.
    Validates credentials and returns the customer profile.
    """
    return customer_auth_controller.authenticate_customer(db, credentials)

# --- SESSION DATA FETCHING ---
@router.get("/profile/{customer_id}", response_model=schemas.CustomerResponse)
def get_customer_session_data(customer_id: int, db: Session = Depends(get_db)):
    """
    Retrieves essential session details by Customer ID.
    Used to persist customer info on the mobile app after a successful login.
    """
    customer_data = customer_auth_controller.get_current_customer_profile(db, customer_id)

    if not customer_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer session data not found"
        )

    return customer_data