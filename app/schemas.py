from pydantic import BaseModel, EmailStr, ConfigDict, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

# --- AUTHENTICATION & OWNER SCHEMAS ---

class OwnerCreate(BaseModel):
    shop_name: str
    address: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    email: str
    role: str
    shop_id: Optional[int] = None
    shop_name: Optional[str] = None
    address: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, exclude_none=True)

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

# --- MACHINE SCHEMAS ---

class MachineBase(BaseModel):
    machine_type: str
    machine_number: int
    status: str = "Available"
    shop_id: int = 1 
    
    # Updated to match DB telemetry for Naga City utility tracking
    accumulated_detergent: float = 0.0   
    accumulated_electricity: float = 0.0  
    accumulated_water: float = 0.0        

class MachineCreate(MachineBase):
    """Used when registering a new unit."""
    pass 

class MachineUpdate(BaseModel):
    """
    Schema for updating hardware configuration or manual status overrides.
    Includes support for accumulated cost updates from the PredictionService.
    """
    status: Optional[str] = None
    remaining_time: Optional[int] = None
    
    accumulated_detergent: Optional[float] = None
    accumulated_electricity: Optional[float] = None
    accumulated_water: Optional[float] = None
    
    current_service_type: Optional[str] = None
    current_price: Optional[float] = None
    profitability_rate: Optional[float] = None
    net_profit_accumulated: Optional[float] = None

class MachineResponse(MachineBase):
    id: int
    total_cycles: int
    remaining_time: int
    
    current_service_type: Optional[str] = "None"
    current_price: float = 0.0
    
    # --- CALCULATED ANALYTICS ---
    # Matches the 'net_profit_accumulated' column in PostgreSQL
    profitability_rate: float = 0.0 
    net_profit_accumulated: float = 0.0 
    
    metrics: Optional[Dict[str, float]] = None 

    model_config = ConfigDict(from_attributes=True)

class MachineNested(BaseModel):
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

    # Hardware Assignment
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    # Service flags
    add_detergent: bool = False
    add_delivery: bool = False
    is_rush: bool = False

    # NEW: Captures actual time from the Service Terminal for peak-hour forecasting
    # This allows the frontend to send the exact click-time of the transaction.
    booking_timestamp: Optional[datetime] = Field(default_factory=datetime.now)

    model_config = ConfigDict(populate_by_name=True)

class BookingStatusUpdate(BaseModel):
    status: str

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
    
    # NEW: Displays the recorded time of booking in the UI
    booking_timestamp: datetime 
    created_at: datetime
    
    shop_id: int 
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None
    
    washer: Optional[MachineNested] = None
    dryer: Optional[MachineNested] = None

    model_config = ConfigDict(from_attributes=True)

# --- DASHBOARD & ANALYTICS SCHEMAS ---

class DashboardStats(BaseModel):
    total_revenue: float
    revenue_trend: str
    utilization_rate: float
    utilization_trend: str
    avg_income: float
    income_trend: str
    pending_bookings: int
    bookings_trend: str
    
    wash_only: int
    dry_only: int
    full_service: int
    total_weight: float
    
    forecast_data: List[Dict[str, Any]]
    optimization: Optional[Dict[str, str]] = None

# --- SETTINGS SCHEMAS ---

class ShopSettingsUpdate(BaseModel):
    rush_rate: Optional[float] = None
    delivery_fee: Optional[float] = None
    detergent_price: Optional[float] = None