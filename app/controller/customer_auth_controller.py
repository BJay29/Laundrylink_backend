import bcrypt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app import models, schemas

def register_customer(db: Session, customer: schemas.CustomerCreate):
    """
    Registers a new customer account for the mobile app.
    Customers are not tied to a shop_id since they can book across shops.
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

    # 3. Create the customer account
    new_customer = models.Customer(
        full_name=customer.full_name,
        email=customer.email,
        mobile_number=customer.mobile_number,
        hashed_password=hashed_pass,
    )
    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)

    return new_customer


def authenticate_customer(db: Session, credentials: schemas.CustomerLogin):
    """
    Authenticates a customer via email and password for the mobile app.
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

    # 3. Check if the account is active
    if not customer.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Contact support."
        )

    # 4. Build response payload
    customer_payload = {
        "id": customer.id,
        "full_name": customer.full_name,
        "email": customer.email,
        "mobile_number": customer.mobile_number,
        "is_active": customer.is_active,
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
    }