from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional

# --- REGISTRATION SCHEMAS ---

class OwnerCreate(BaseModel):
    """
    Schema for internal/backend registration of Shop Owners.
    Used via Thunder Client to populate the database without a frontend form.
    """
    shop_name: str
    address: str
    email: EmailStr
    password: str

# --- AUTHENTICATION SCHEMAS ---

class UserLogin(BaseModel):
    """ 
    Standard login credentials for both Web and Mobile.
    Used to authenticate Owners and Staff against the PostgreSQL database.
    """
    email: EmailStr
    password: str

# --- DATA REPRESENTATION (RESPONSE) SCHEMAS ---

class UserResponse(BaseModel):
    """ 
    Simplified user response focused on shop identification.
    Returns only the essential data needed for the dashboard context.
    """
    email: str
    
    # Shop-specific details required for the frontend
    shop_id: Optional[int] = None
    shop_name: Optional[str] = None
    address: Optional[str] = None

    model_config = ConfigDict(
        from_attributes=True,
        exclude_none=True 
    )

class LoginResponse(BaseModel):
    """
    The final JSON structure sent to the React and Flutter frontends.
    Contains the bearer token and the simplified user/shop object.
    """
    access_token: str
    token_type: str = "bearer"
    user: UserResponse