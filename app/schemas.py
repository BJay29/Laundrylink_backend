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
    # Ginawa nating default 1 para laging may value kahit galing sa simpleng request
    shop_id: int = 1 

class MachineCreate(MachineBase):
    pass # Inherits everything from MachineBase including shop_id

class MachineUpdate(BaseModel):
    status: Optional[str] = None
    remaining_time: Optional[int] = None
    shop_id: Optional[int] = None

class MachineResponse(MachineBase):
    id: int
    total_cycles: int
    avg_detergent: float
    avg_electricity: float
    avg_water: float
    remaining_time: int

    model_config = ConfigDict(from_attributes=True)

# --- MACHINE NESTED ---
# Ginagamit para sa nested objects sa BookingResponse.
# Sinisiguro nito na hindi mag-error ang display sa Service Terminal at Dashboard.
class MachineNested(BaseModel):
    id: int
    machine_type: str
    machine_number: int
    status: str
    shop_id: int # Mahalaga ito para sa validation sa frontend

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
    # Default sa 1 para mag-match sa auto-fix logic natin
    shop_id: int = 1 

    # Siniguradong tumatanggap ng null/None kung isang machine lang ang pinili
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

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
    shop_id: int # Sinisigurado na laging kasama ang shop reference
    
    # IDs para sa internal logic
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    # Pag-fetch ng booking, automatic kasama ang machine details (nested objects).
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

# --- SETTINGS SCHEMAS ---
class ShopSettingsUpdate(BaseModel):
    rush_rate: Optional[float] = None
    delivery_fee: Optional[float] = None
    detergent_price: Optional[float] = None