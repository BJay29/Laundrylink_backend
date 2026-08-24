import bcrypt
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app import models, schemas
from app.services.email_service import generate_verification_code, send_verification_email

CODE_EXPIRY_MINUTES = 10


def register_customer(db: Session, customer: schemas.CustomerCreate):
    """
    Registers a new customer account for the mobile app.
    Customers are not tied to a shop_id since they can book across shops.
    Account starts as unverified; a 6-digit code is emailed for verification.
    """
    # 1. Check if the email is already in use
    db_customer = db.query(models.Customer).filter(models.Customer.email == customer.email).first()
    if db_customer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # 2. Hash the password
    hashed_pass = bcrypt.hashpw(
        customer.password.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')

    # 3. Generate verification code
    code = generate_verification_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=CODE_EXPIRY_MINUTES)

    # 4. Create the customer account (unverified)
    new_customer = models.Customer(
        full_name=customer.full_name,
        email=customer.email,
        mobile_number=customer.mobile_number,
        hashed_password=hashed_pass,
        is_verified=False,
        verification_code=code,
        verification_expires_at=expires_at,
    )
    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)

    # 5. Send verification email (best-effort — account still created if email fails)
    email_sent = send_verification_email(new_customer.email, new_customer.full_name, code)
    if not email_sent:
        print(f"Warning: verification email failed to send for {new_customer.email}")

    return new_customer


def verify_customer_email(db: Session, payload: schemas.CustomerVerifyEmail):
    """
    Validates the 6-digit code submitted by the customer and activates the account.
    """
    customer = db.query(models.Customer).filter(models.Customer.email == payload.email).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found"
        )

    if customer.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is already verified"
        )

    if not customer.verification_code or customer.verification_code != payload.code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code"
        )

    expires_at = customer.verification_expires_at
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if not expires_at or datetime.now(timezone.utc) > expires_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification code has expired. Please request a new one."
        )

    customer.is_verified = True
    customer.verification_code = None
    customer.verification_expires_at = None
    db.commit()
    db.refresh(customer)

    return customer


def resend_verification_code(db: Session, payload: schemas.CustomerResendCode):
    """
    Generates and sends a new 6-digit verification code to the customer.
    """
    customer = db.query(models.Customer).filter(models.Customer.email == payload.email).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account not found"
        )

    if customer.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account is already verified"
        )

    code = generate_verification_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=CODE_EXPIRY_MINUTES)

    customer.verification_code = code
    customer.verification_expires_at = expires_at
    db.commit()

    email_sent = send_verification_email(customer.email, customer.full_name, code)
    if not email_sent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email. Please try again."
        )

    return {"message": "A new verification code has been sent to your email."}


def authenticate_customer(db: Session, credentials: schemas.CustomerLogin):
    """
    Authenticates a customer via email and password for the mobile app.
    Blocks login until the account has been verified.
    Returns a unified payload consistent with the owner-side login response.
    """

    # 1. Fetch customer by email
    customer = db.query(models.Customer).filter(
        models.Customer.email == credentials.email
    ).first()

    # 2. Verify existence and password
    if not customer:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid email or password"
        )

    if not bcrypt.checkpw(
        credentials.password.encode('utf-8'),
        customer.hashed_password.encode('utf-8')
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid email or password"
        )

    # 3. Check if the account has been verified
    if not customer.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before logging in."
        )

    # 4. Check if the account is active
    if not customer.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Contact support."
        )

    # 5. Build response payload
    customer_payload = {
        "id": customer.id,
        "full_name": customer.full_name,
        "email": customer.email,
        "mobile_number": customer.mobile_number,
        "is_active": customer.is_active,
        "is_verified": customer.is_verified,
    }

    return {
        "access_token": "token_placeholder",  # TODO: replace with real JWT
        "token_type": "bearer",
        "customer": customer_payload
    }


def get_current_customer_profile(db: Session, customer_id: int):
    """
    Fetches basic profile info for the current customer session.
    """
    customer = db.query(models.Customer).filter(models.Customer.id == customer_id).first()

    if not customer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found"
        )

    return {
        "id": customer.id,
        "full_name": customer.full_name,
        "email": customer.email,
        "mobile_number": customer.mobile_number,
        "is_active": customer.is_active,
        "is_verified": customer.is_verified,
    }