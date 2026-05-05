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
    machine_type: str # 'Washer' or 'Dryer'
    machine_number: int
    status: str = "Available"

class MachineCreate(MachineBase):
    shop_id: int

class MachineUpdate(BaseModel):
    status: Optional[str] = None
    remaining_time: Optional[int] = None

class MachineMiniResponse(BaseModel):
    id: int
    machine_type: str
    machine_number: int

    model_config = ConfigDict(from_attributes=True)

class MachineResponse(MachineBase):
    id: int
    shop_id: int
    # Ginawang Optional para hindi mag-error (500) kung wala sa DB
    total_cycles: Optional[int] = 0
    avg_detergent: Optional[float] = 0.0
    avg_electricity: Optional[float] = 0.0
    avg_water: Optional[float] = 0.0
    remaining_time: Optional[int] = 0

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
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None
    # Relationship fields
    washer: Optional[MachineMiniResponse] = None
    dryer: Optional[MachineMiniResponse] = None

    model_config = ConfigDict(from_attributes=True)

class StatusUpdate(BaseModel):
    status: str

# --- DATA REPRESENTATION SCHEMAS ---

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