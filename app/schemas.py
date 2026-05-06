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
    shop_id: int = 1 
    
    # Cumulative consumption totals - these reflect the overall usage of the hardware
    total_electricity: float = 0.0 # Total PHP/kWh consumed
    total_water: float = 0.0       # Total PHP/Liters consumed
    total_detergent: float = 0.0     # Total PHP/ml consumed

class MachineCreate(MachineBase):
    pass 

class MachineUpdate(BaseModel):
    status: Optional[str] = None
    remaining_time: Optional[int] = None
    shop_id: Optional[int] = None
    # Allows manual adjustment of cumulative costs if maintenance/reset occurs
    total_electricity: Optional[float] = None
    total_water: Optional[float] = None
    total_detergent: Optional[float] = None

class PredictionMetrics(BaseModel):
    """
    Used for real-time cost estimation during the booking process 
    based on the selected service type (Full Service, Titan, etc.)
    """
    detergent_cost: float
    electricity_cost: float
    water_cost: float
    total_overhead: float
    is_active_consumption: bool

class MachineResponse(MachineBase):
    id: int
    total_cycles: int
    remaining_time: int
    
    # Provides detailed metrics for charts and the Machine Hub UI
    metrics: Optional[Dict[str, float]] = None 

    model_config = ConfigDict(from_attributes=True)

# --- MACHINE NESTED ---
class MachineNested(BaseModel):
    """Simplified machine view used within Booking responses"""
    id: int
    machine_type: str
    machine_number: int
    status: str
    shop_id: int 

    model_config = ConfigDict(from_attributes=True)

# --- BOOKING SCHEMAS ---

class BookingCreate(BaseModel):
    customer_name: str
    service_type: str # Options: 'Full Service', 'Titan Wash', 'Regular Wash', 'Comforter'
    category: str
    weight: float
    loads: int
    total_price: float
    booking_mode: str
    shop_id: int = 1 

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
    shop_id: int 
    
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

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
    """Global shop configuration for cost calculation logic"""
    rush_rate: Optional[float] = None
    delivery_fee: Optional[float] = None
    detergent_price: Optional[float] = None