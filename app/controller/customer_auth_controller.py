import bcrypt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app import models, schemas
from app.security import create_customer_access_token


def register_customer(db: Session, customer: schemas.CustomerCreate):
    """
    Registers a new customer account for the mobile app.
    Customers are not tied to a shop_id since they can book across shops.

    UPDATED: Tinanggal na ang email verification step. Awtomatikong
    is_verified=True na ang account sa mismong oras ng pagpaparehistro —
    walang na-ge-generate na 6-digit code, walang email na pinapadala.
    Ito ay pansamantalang desisyon habang wala pang gumaganang
    production-ready na email delivery (SMTP blocked ng Render Free
    Tier; email API provider hindi pa fully na-se-setup).
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

    # 3. Create the customer account — VERIFIED AGAD, walang OTP/email step.
    new_customer = models.Customer(
        full_name=customer.full_name,
        email=customer.email,
        mobile_number=customer.mobile_number,
        hashed_password=hashed_pass,
        is_verified=True,   # <-- dating False + code/email flow, ngayon True agad
        verification_code=None,
        verification_expires_at=None,
    )
    db.add(new_customer)
    db.commit()
    db.refresh(new_customer)

    return new_customer


def authenticate_customer(db: Session, credentials: schemas.CustomerLogin):
    """
    Authenticates a customer via email and password for the mobile app.
    Returns a REAL signed JWT (type=customer) instead of a placeholder,
    consistent with the owner-side login response.

    NOTE: Wala nang is_verified check dito — lahat ng bagong customer ay
    verified na agad sa registration. Nananatili pa rin ang column sa DB
    para hindi na kailangang mag-migrate/mag-alter table, pero hindi na
    ito ginagamit bilang gate para sa login.
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
        "is_verified": customer.is_verified,
    }

    # 5. Generate a REAL signed JWT with "type": "customer" —
    #    hindi ito magagamit para mag-access ng shop-owner-only
    #    endpoints kahit valid ang signature nito.
    token = create_customer_access_token(customer_id=customer.id)

    return {
        "access_token": token,
        "token_type": "bearer",
        "customer": customer_payload
    }


# NOTE: Tinanggal na ang verify_customer_email() at resend_verification_code()
# — hindi na kailangan dahil walang OTP/email verification step. Kung sa
# hinaharap ay babalikan ang email verification (hal. kapag gumagana na
# ang production email delivery), pwedeng ibalik ang mga functions na ito
# gamit ang git history bilang reference.