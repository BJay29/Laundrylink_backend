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
    # Operational efficiency tracking - default consumption rates per hardware cycle
    avg_detergent: float = 50.0  # ml per cycle
    avg_electricity: float = 1.2 # kWh per cycle
    avg_water: float = 60.0      # Liters per cycle

class MachineCreate(MachineBase):
    pass 

class MachineUpdate(BaseModel):
    status: Optional[str] = None
    remaining_time: Optional[int] = None
    shop_id: Optional[int] = None
    # Update machine efficiency if hardware is upgraded or parts are replaced
    avg_detergent: Optional[float] = None
    avg_electricity: Optional[float] = None
    avg_water: Optional[float] = None
    # Real-time assignment fields for live dashboard monitoring
    current_service_type: Optional[str] = None
    current_price: Optional[float] = None

class PredictionMetrics(BaseModel):
    """
    Structure for the calculated costs returned by the PredictionService.
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
    # Real-time telemetry data for Dashboard display
    current_service_type: Optional[str] = "None"
    current_price: float = 0.0
    
    # --- CALCULATED ANALYTICS ---
    # These fields are computed by the service layer before returning to UI
    profitability_rate: float = 0.0      # Pure profit margin percentage (%)
    net_profit_accumulated: float = 0.0 # Lifetime earnings after overhead deductions (₱)
    
    # Dictionary carrying the breakdown of overhead costs (Electricity, Water, Detergent)
    metrics: Optional[Dict[str, float]] = None 

    model_config = ConfigDict(from_attributes=True)

# --- MACHINE NESTED ---
class MachineNested(BaseModel):
    """
    Simplified Machine view used within Booking responses to prevent circular imports.
    """
    id: int
    machine_type: str
    machine_number: int
    status: str
    shop_id: int 

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
    shop_id: int = 1 

    # Linking to specific hardware units (IDs must exist in the machines table)
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    # Service add-ons
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
    
    # Nested hardware details to show Machine Numbers in the terminal/history
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