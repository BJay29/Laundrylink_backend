from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app import schemas, models
from app.controller import customer_auth_controller
from app.security import get_current_customer

router = APIRouter(
    prefix="/customer",
    tags=["Customer Authentication"]
)

# --- CUSTOMER REGISTRATION (Mobile App) ---
@router.post("/register", response_model=schemas.CustomerResponse)
def register_customer(customer: schemas.CustomerCreate, db: Session = Depends(get_db)):
    """
    Endpoint for customer self-registration via the Flutter mobile app.

    UPDATED: Awtomatikong verified na agad ang account sa oras ng
    pagpaparehistro — tinanggal na ang email verification step
    (walang na-ge-generate na code, walang email na pinapadala).
    """
    return customer_auth_controller.register_customer(db, customer)


# --- CUSTOMER LOGIN (Mobile App) ---
@router.post("/login", response_model=schemas.CustomerLoginResponse)
def login(credentials: schemas.CustomerLogin, db: Session = Depends(get_db)):
    """
    Authentication endpoint for the Flutter mobile app.
    Validates credentials and returns a REAL JWT + the customer profile.
    """
    return customer_auth_controller.authenticate_customer(db, credentials)


# --- SESSION DATA FETCHING (PROTECTED, SELF ONLY) ---
@router.get("/profile", response_model=schemas.CustomerResponse)
def get_my_customer_profile(current_customer: models.Customer = Depends(get_current_customer)):
    """
    Retrieves session details of the CURRENTLY LOGGED-IN customer only,
    based on the verified JWT sent in the Authorization header.
    """
    return current_customer


# NOTE: Tinanggal na ang "/verify" at "/resend-verification" endpoints —
# hindi na kailangan dahil walang email verification step. Tinanggal
# na rin dati ang "/test-email/{test_email}" debug endpoint (nag-expose
# ito ng SMTP config info nang walang authentication).