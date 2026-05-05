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

# --- MACHINE NESTED ---
# Ginagamit ito para sa nested objects sa BookingResponse para hindi mag-"UNASSIGNED" 
# ang display sa Service Terminal at Dashboard.
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

    # Siniguradong tumatanggap ng null/None kung isang machine lang ang pinili
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    add_detergent: bool = False
    add_delivery: bool = False
    is_rush: bool = False

    # Mahalaga ito para sa conversion ng JSON keys mula sa frontend
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
    
    # IDs para sa internal logic
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    # Eto ang "Magic" fields: Pag-fetch ng booking, automatic kasama ang machine details.
    # Siguraduhin na sa models.py, ang relationship names ay 'washer' at 'dryer'.
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

# --- SETTINGS SCHEMAS (Optional pero baka kailanganin mo sa dashboard) ---
class ShopSettingsUpdate(BaseModel):
    rush_rate: Optional[float] = None
    delivery_fee: Optional[float] = None
    detergent_price: Optional[float] = None