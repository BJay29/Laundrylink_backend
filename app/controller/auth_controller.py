import bcrypt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app import models, schemas

def create_customer(db: Session, user: schemas.CustomerCreate):
    """
    Handles customer registration by creating a base user and a linked profile.
    Address is initialized as None because it is not required during sign-up.
    """
    # 1. Check if the email is already in use
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # 2. Hash the password for security
    hashed_pass = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    # 3. Create and save the base user record
    new_user = models.User(
        email=user.email,
        password_hash=hashed_pass,
        role="customer"
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # 4. Create and save the customer profile (address defaults to None)
    new_profile = models.CustomerProfile(
        user_id=new_user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        phone_number=user.phone_number,
        address=None  
    )
    db.add(new_profile)
    db.commit()
    db.refresh(new_profile)

    # 5. Attach profile data to the user object for the response
    new_user.first_name = new_profile.first_name
    new_user.last_name = new_profile.last_name
    new_user.phone_number = new_profile.phone_number
    new_user.address = new_profile.address
    
    return new_user

def create_owner(db: Session, user: schemas.OwnerCreate):
    """
    Handles shop owner registration by creating a shop and a linked user account.
    """
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # 1. Create the Shop entity first
    new_shop = models.Shop(shop_name=user.shop_name)
    db.add(new_shop)
    db.commit()
    db.refresh(new_shop)

    # 2. Create the Owner account linked to the new shop
    hashed_pass = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    new_user = models.User(
        email=user.email,
        password_hash=hashed_pass,
        role="owner",
        shop_id=new_shop.id
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # 3. Attach shop name for the response
    new_user.shop_name = new_shop.shop_name
    
    return new_user

def authenticate_user(db: Session, credentials: schemas.UserLogin):
    """
    Authenticates users and constructs a unified payload for the frontend.
    """
    user = db.query(models.User).filter(models.User.email == credentials.email).first()

    if not user or not bcrypt.checkpw(credentials.password.encode('utf-8'), user.password_hash.encode('utf-8')):
        raise HTTPException(status_code=403, detail="Invalid Credentials")

    user_payload = {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "shop_id": user.shop_id,
        "shop_name": user.shop.shop_name if user.shop else None
    }

    if user.role == "customer" and user.customer_profile:
        user_payload.update({
            "first_name": user.customer_profile.first_name,
            "last_name": user.customer_profile.last_name,
            "phone_number": user.customer_profile.phone_number,
            "address": user.customer_profile.address
        })

    return {
        "access_token": "token_placeholder", 
        "token_type": "bearer",
        "user": user_payload
    }

def update_user_profile(db: Session, user_id: int, profile_data: schemas.UserUpdate):
    """
    Updates the customer's profile information. 
    Strictly filters for users with the 'customer' role.
    """
    # 1. Fetch the user record
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        return None

    # 2. Ensure only customers can update profile data
    if db_user.role == "customer" and db_user.customer_profile:
        profile = db_user.customer_profile
        
        # Only update fields that were actually sent in the request
        update_data = profile_data.model_dump(exclude_unset=True)
        
        for key, value in update_data.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        
        db.commit()
        db.refresh(profile)
        
        # 3. Synchronize updated profile fields back to the user object for response
        db_user.first_name = profile.first_name
        db_user.last_name = profile.last_name
        db_user.phone_number = profile.phone_number
        db_user.address = profile.address
        
        return db_user
        
    return None # Return None if user is an Owner or has no profile