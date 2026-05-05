from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, List
from datetime import datetime

# --- REGISTRATION SCHEMAS ---

class OwnerCreate(BaseModel):
    shop_name: str
    address: str
    email: EmailStr
    password: str

# --- AUTHENTICATION SCHEMAS ---

class UserLogin(BaseModel):
    email: EmailStr
    password: str

# --- MACHINE SCHEMAS ---

class MachineBase(BaseModel):
    machine_type: str
    machine_number: int
    status: str = "Available"

class MachineCreate(MachineBase):
    shop_id: int

class MachineUpdate(BaseModel):
    status: Optional[str] = None
    remaining_time: Optional[int] = None

class MachineResponse(MachineBase):
    id: int
    shop_id: int
    total_cycles: int
    avg_detergent: float
    avg_electricity: float
    avg_water: float
    remaining_time: int

    model_config = ConfigDict(from_attributes=True)

# --- MACHINE NESTED (used inside BookingResponse) ---
# FIX: This is the nested object returned with each booking
# so the frontend can display W1, D3, etc. correctly
class MachineNested(BaseModel):
    """
    Minimal machine info embedded inside a BookingResponse.
    Gives the frontend the machine_number to display (W1, D3, etc.)
    instead of relying on the raw foreign key integer.
    """
    id: int
    machine_type: str       # 'Washer' or 'Dryer'
    machine_number: int     # This is what the frontend uses to display W1, D2, etc.
    status: str

    model_config = ConfigDict(from_attributes=True)

# --- BOOKING SCHEMAS ---

class BookingCreate(BaseModel):
    customer_name: str
    service_type: str
    category: str
    weight: float
    loads: int
    total_price: float
    booking_mode: str

    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    add_detergent: bool = False
    add_delivery: bool = False
    is_rush: bool = False

class BookingResponse(BaseModel):
    """
    Full booking response sent to the frontend.
    FIX: Includes nested washer/dryer objects so the Service Terminal
    can display the correct machine label (W1, D3) instead of raw IDs.
    """
    id: int
    customer_name: str
    service_type: str
    category: str
    weight: float
    loads: int
    total_price: float
    status: str
    booking_mode: str
    created_at: datetime

    # Raw foreign keys (still included for reference)
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    # FIX: Nested machine objects — frontend uses these for display
    # SQLAlchemy will populate these via the relationship()
    washer: Optional[MachineNested] = None
    dryer: Optional[MachineNested] = None

    model_config = ConfigDict(from_attributes=True)

# --- USER / AUTH SCHEMAS ---

class UserResponse(BaseModel):
    email: str
    role: str
    shop_id: Optional[int] = None
    shop_name: Optional[str] = None
    address: Optional[str] = None

    model_config = ConfigDict(
        from_attributes=True,
        exclude_none=True
    )

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
