from pydantic import BaseModel, EmailStr, ConfigDict, Field
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

# --- MACHINE NESTED (ginagamit para sa Display sa Booking Table) ---
class MachineNested(BaseModel):
    id: int
    machine_type: str
    machine_number: int
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

    # FIX: Tinanggal ang validation_alias dahil "washer_id" na ang pinapasa ng frontend mo 
    # base sa image_026bbd.png. Ginawa nating Optional[int] para siguradong Number ang tanggap.
    washer_id: Optional[int] = Field(None)
    dryer_id: Optional[int] = Field(None)

    add_detergent: bool = False
    add_delivery: bool = False
    is_rush: bool = False

    model_config = ConfigDict(populate_by_name=True)

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

    # Eto ang kailangan para hindi mag-"UNASSIGNED" sa table (image_02737f.png)
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