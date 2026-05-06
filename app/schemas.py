from pydantic import BaseModel, EmailStr, ConfigDict, Field
from typing import Optional, List, Dict
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
    # Defaulting to 1 to ensure compatibility with simple requests
    shop_id: int = 1 

class MachineCreate(MachineBase):
    pass # Inherits everything from MachineBase including shop_id

class MachineUpdate(BaseModel):
    status: Optional[str] = None
    remaining_time: Optional[int] = None
    shop_id: Optional[int] = None

# New schema to structure the ML/Prediction results
class PredictionMetrics(BaseModel):
    detergent_cost: float
    electricity_cost: float
    water_cost: float
    total_overhead: float
    is_active_consumption: bool

class MachineResponse(MachineBase):
    id: int
    total_cycles: int
    # These fields can remain for raw averages
    avg_detergent: float
    avg_electricity: float
    avg_water: float
    remaining_time: int
    # Added metrics to hold the calculated logic from prediction_service.py
    metrics: Optional[Dict[str, float]] = None 

    model_config = ConfigDict(from_attributes=True)

# --- MACHINE NESTED ---
# Used for nested objects in BookingResponse to prevent display errors
class MachineNested(BaseModel):
    id: int
    machine_type: str
    machine_number: int
    status: str
    shop_id: int # Important for frontend validation

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
    # Default set to 1 to match auto-fix logic
    shop_id: int = 1 

    # Accepts null if only one machine is selected
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
    shop_id: int # Ensures shop reference is always included
    
    # IDs for internal logic
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    # Automatically includes machine details when fetching booking
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