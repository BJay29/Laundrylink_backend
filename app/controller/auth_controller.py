import bcrypt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app import models, schemas

def create_owner(db: Session, user: schemas.OwnerCreate):
    """
    Backend-only registration for Shop Owners.
    Creates a new shop entity and links the owner account to it.
    Used for populating the database via Thunder Client.
    """
    # 1. Check if the email is already in use
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Email already registered"
        )

    # 2. Create the Shop entity first
    new_shop = models.Shop(
        shop_name=user.shop_name,
        address=user.address
    )
    db.add(new_shop)
    db.commit()
    db.refresh(new_shop)

    # 3. Create the Owner account linked to the new shop
    hashed_pass = bcrypt.hashpw(
        user.password.encode('utf-8'), 
        bcrypt.gensalt()
    ).decode('utf-8')
    
    new_user = models.User(
        email=user.email,
        hashed_password=hashed_pass, 
        role="owner",
        shop_id=new_shop.id
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # 4. Attach shop details for the response
    new_user.shop_name = new_shop.shop_name
    new_user.address = new_shop.address
    
    return new_user

def authenticate_user(db: Session, credentials: schemas.UserLogin):
    """
    Authenticates administrative users (Owners/Staff) via email and password.
    Returns a unified payload for both React and Flutter.
    """
    
    # 1. Fetch user by email
    user = db.query(models.User).filter(
        models.User.email == credentials.email
    ).first()

    # 2. Verify existence and password
    # Added defensive check to avoid AttributeError if user is None
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Invalid email or password"
        )
        
    if not bcrypt.checkpw(
        credentials.password.encode('utf-8'), 
        user.hashed_password.encode('utf-8')
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Invalid email or password"
        )

    # 3. Check if user is active
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is inactive. Contact your administrator."
        )

    # 4. Build response payload with safe checks for 'shop' relationship
    user_payload = {
        "email": user.email,
        "role": user.role,                                         
        "shop_id": user.shop_id,
        "shop_name": getattr(user.shop, 'shop_name', None) if user.shop else None,
        "address": getattr(user.shop, 'address', None) if user.shop else None,
    }

    return {
        "access_token": "token_placeholder",  # TODO: replace with real JWT
        "token_type": "bearer",
        "user": user_payload
    }

def get_current_user_profile(db: Session, user_id: int):
    """
    Fetches basic shop and user info for the current session.
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="User not found"
        )

    return {
        "email": user.email,
        "role": user.role,
        "shop_id": user.shop_id,
        "shop_name": getattr(user.shop, 'shop_name', None) if user.shop else None,
        "address": getattr(user.shop, 'address', None) if user.shop else None,
    }