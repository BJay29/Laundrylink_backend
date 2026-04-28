from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional

# --- REGISTRATION SCHEMAS ---

class CustomerCreate(BaseModel):
    """ 
    Schema for mobile app registration (Customers).
    Inalis na ang address dito para hindi na kailangan i-input sa sign-up.
    """
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    phone_number: str

class OwnerCreate(BaseModel):
    """ Schema for web dashboard registration (Shop Owners) """
    shop_name: str
    email: EmailStr
    password: str

# --- AUTHENTICATION SCHEMAS ---

class UserLogin(BaseModel):
    """ Standard login credentials for all users """
    email: EmailStr
    password: str

# --- UPDATE SCHEMAS ---

class UserUpdate(BaseModel):
    """ 
    Dito na papasok ang address. 
    Gagamitin ito sa 'Edit Profile' screen ng Mobile App.
    """
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None

class ShopUpdate(BaseModel):
    """ For updating Laundry Shop information (Owner only) """
    shop_name: Optional[str] = None
    address: Optional[str] = None

# --- DATA REPRESENTATION SCHEMAS ---

class UserResponse(BaseModel):
    """ 
    Unified response schema for the 'user' object.
    Dahil sa exclude_none=True, hindi lalabas ang 'null' fields sa Thunder Client.
    """
    id: int
    email: str
    role: str
    
    # Shop fields (Visible only if User is an Owner)
    shop_id: Optional[int] = None
    shop_name: Optional[str] = None
    
    # Profile fields (Visible only if User is a Customer)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    address: Optional[str] = None

    model_config = ConfigDict(
        from_attributes=True,
        exclude_none=True # Ito ang magtatanggal ng 'address' field sa JSON kung ito ay null.
    )

class LoginResponse(BaseModel):
    """
    Final JSON response structure for React and Flutter.
    Matches authService.js requirements.
    """
    access_token: str
    token_type: str = "bearer"
    user: UserResponse