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
    
    # Updated to match DB telemetry for utility cost tracking
    accumulated_detergent: float = 0.0   
    accumulated_electricity: float = 0.0  
    accumulated_water: float = 0.0         

class MachineCreate(MachineBase):
    """Used for initial hardware registration."""
    pass 

class MachineUpdate(BaseModel):
    """
    Schema for updating hardware state or manual maintenance overrides.
    Supports real-time cost updates from the PredictionService.
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
    # Tracks financial performance for the Monitoring Hub
    profitability_rate: float = 0.0 
    net_profit_accumulated: float = 0.0 
    
    metrics: Optional[Dict[str, float]] = None 

    model_config = ConfigDict(from_attributes=True)

class MachineNested(BaseModel):
    """Simplified machine view used inside Booking responses."""
    id: int
    machine_type: str
    machine_number: int
    status: str
    shop_id: int 

    model_config = ConfigDict(from_attributes=True)

# --- BOOKING SCHEMAS ---

class BookingCreate(BaseModel):
    """
    Schema for creating a laundry transaction.
    Now includes booking_timestamp for Peak-Hour Forecasting.
    """
    customer_name: str
    service_type: str
    category: str
    weight: float
    loads: int
    total_price: float
    booking_mode: str
    shop_id: int = 1 

    # Hardware Assignments
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    # Service flags
    add_detergent: bool = False
    add_delivery: bool = False
    is_rush: bool = False

    # AI DATA POINT: Captures the exact creation time for the forecasting model
    booking_timestamp: Optional[datetime] = Field(default=None)

    model_config = ConfigDict(populate_by_name=True)

class BookingStatusUpdate(BaseModel):
    """Used to move transactions through the lifecycle (e.g., Ready -> Claimed)."""
    status: str

class BookingResponse(BaseModel):
    """
    Full response schema for the Service Terminal.
    Optimized with nested machine objects and formatted timestamps.
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
    
    # AI Prediction Metrics: Crucial for Peak-Hour Charts
    booking_timestamp: Optional[datetime] = None
    created_at: datetime
    
    shop_id: int 
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None
    
    # UI Helpers: Returns hardware labels (e.g., W1, D5) to the terminal table
    washer_number: Optional[int] = None
    dryer_number: Optional[int] = None
    
    # Nested objects for detailed hardware state
    washer: Optional[MachineNested] = None
    dryer: Optional[MachineNested] = None

    model_config = ConfigDict(from_attributes=True)

# --- DASHBOARD & ANALYTICS SCHEMAS ---

class DashboardStats(BaseModel):
    """High-level metrics for the Owner's Overview page."""
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
    
    # Forecasting data for Chart.js/Recharts integration
    forecast_data: List[Dict[str, Any]]
    optimization: Optional[Dict[str, str]] = None

# --- SETTINGS SCHEMAS ---

class ShopSettingsUpdate(BaseModel):
    """Adjustable business parameters for the Shop Owner."""
    rush_rate: Optional[float] = None
    delivery_fee: Optional[float] = None
    detergent_price: Optional[float] = None