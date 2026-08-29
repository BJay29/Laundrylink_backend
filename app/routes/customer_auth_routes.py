from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app import schemas, models
from app.controller import customer_auth_controller
from app.security import get_current_customer  # ⬅️ BAGONG IMPORT

router = APIRouter(
    prefix="/customer",
    tags=["Customer Authentication"]
)

# --- CUSTOMER REGISTRATION (Mobile App) ---
@router.post("/register", response_model=schemas.CustomerResponse)
def register_customer(customer: schemas.CustomerCreate, db: Session = Depends(get_db)):
    """
    Endpoint for customer self-registration via the Flutter mobile app.
    Creates an unverified customer account and emails a 6-digit verification code.
    """
    return customer_auth_controller.register_customer(db, customer)


# --- EMAIL VERIFICATION ---
@router.post("/verify")
def verify_email(payload: schemas.CustomerVerifyEmail, db: Session = Depends(get_db)):
    """
    Validates the 6-digit code submitted by the customer and activates the account.
    """
    return customer_auth_controller.verify_customer_email(db, payload)


# --- RESEND VERIFICATION CODE ---
@router.post("/resend-verification")
def resend_verification(payload: schemas.CustomerResendCode, db: Session = Depends(get_db)):
    """
    Sends a new 6-digit verification code to the customer's email,
    used when the original code expired or was not received.
    """
    return customer_auth_controller.resend_verification_code(db, payload)


# --- CUSTOMER LOGIN (Mobile App) ---
@router.post("/login", response_model=schemas.CustomerLoginResponse)
def login(credentials: schemas.CustomerLogin, db: Session = Depends(get_db)):
    """
    Authentication endpoint for the Flutter mobile app.
    Validates credentials and returns a REAL JWT + the customer profile.
    Login is blocked until the account's email has been verified.
    """
    return customer_auth_controller.authenticate_customer(db, credentials)


# --- SESSION DATA FETCHING (PROTECTED, SELF ONLY) ---
@router.get("/profile", response_model=schemas.CustomerResponse)
def get_my_customer_profile(current_customer: models.Customer = Depends(get_current_customer)):
    """
    Retrieves session details of the CURRENTLY LOGGED-IN customer only,
    based on the verified JWT sent in the Authorization header.

    Dating "/profile/{customer_id}" ay open sa kahit sino, basta alam
    ang isang valid customer ID (1, 2, 3...) — walang authentication
    check. Ngayon, base na sa verified JWT ang result, kaya imposibleng
    makita ng isang customer ang profile ng iba.
    """
    return current_customer


# NOTE: Tinanggal na ang "/test-email/{test_email}" debug endpoint.
# Nag-expose ito ng SMTP config info (env var presence) nang walang
# authentication — dapat lang ito naka-enable habang nagte-test,
# at tinanggal na ngayong secure na ang buong auth flow.