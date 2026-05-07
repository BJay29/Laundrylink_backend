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
    
    # FIXED: Removed hardcoded defaults here to prevent ghost costs on new machines.
    # These should be 0.0 by default unless specifically set during creation or update.
    avg_detergent: float = 0.0   
    avg_electricity: float = 0.0  
    avg_water: float = 0.0        

class MachineCreate(MachineBase):
    """
    Used when registering a new unit. 
    Defaults are set to 0.0 via MachineBase.
    """
    pass 

class MachineUpdate(BaseModel):
    """
    Schema for updating hardware configuration or manual status overrides.
    """
    status: Optional[str] = None
    remaining_time: Optional[int] = None
    avg_detergent: Optional[float] = None
    avg_electricity: Optional[float] = None
    avg_water: Optional[float] = None
    
    # Telemetry updates for real-time monitoring
    current_service_type: Optional[str] = None
    current_price: Optional[float] = None
    profitability_rate: Optional[float] = None
    net_profit_accumulated: Optional[float] = None

class MachineResponse(MachineBase):
    id: int
    total_cycles: int
    remaining_time: int  # Exact countdown for the dashboard
    
    # Live operational data
    current_service_type: Optional[str] = "None"
    current_price: float = 0.0
    
    # --- CALCULATED ANALYTICS ---
    profitability_rate: float = 0.0 
    net_profit_accumulated: float = 0.0 
    
    # This Dict holds the calculated costs (detergent_cost, electricity_cost, etc.)
    # The PredictionService should populate this only based on ACTUAL bookings.
    metrics: Optional[Dict[str, float]] = None 

    model_config = ConfigDict(from_attributes=True)

class MachineNested(BaseModel):
    """Simplified view for inclusion within Booking responses."""
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

    # Service flags affecting duration and cost analytics
    add_detergent: bool = False
    add_delivery: bool = False
    is_rush: bool = False

    model_config = ConfigDict(populate_by_name=True)

class BookingStatusUpdate(BaseModel):
    """Updates lifecycle (e.g., Pending -> In Progress -> Ready -> Claimed)."""
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
    created_at: datetime
    shop_id: int 
    
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None
    
    # Relationship nesting for labels like W1 or D2 in the Service Terminal
    washer: Optional[MachineNested] = None
    dryer: Optional[MachineNested] = None

    model_config = ConfigDict(from_attributes=True)

# --- DASHBOARD & ANALYTICS SCHEMAS ---

class DashboardStats(BaseModel):
    """Consolidated schema for the Overview Dashboard."""
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
    
    # 7-Day Forecast Data
    forecast_data: List[Dict[str, Any]]
    
    # AI Optimization Tips
    optimization: Optional[Dict[str, str]] = None

# --- SETTINGS SCHEMAS ---

class ShopSettingsUpdate(BaseModel):
    rush_rate: Optional[float] = None
    delivery_fee: Optional[float] = None
    detergent_price: Optional[float] = None