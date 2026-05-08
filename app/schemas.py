from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator
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

# --- SETTINGS SCHEMAS ---
# These schemas handle the core logic for Service Pricing and Utility Rates.

class SettingBase(BaseModel):
    """Base settings schema containing pricing and operational rates."""
    wash_only_price: float = 40.0
    dry_only_price: float = 30.0
    full_service_price: float = 60.0
    
    # Utility Unit Rates for AI/ML Cost Prediction
    electricity_rate: float = 12.0  # PHP per kWh
    water_rate: float = 50.0        # PHP per Cubic Meter
    detergent_cost_per_load: float = 10.0
    
    off_peak_hours: str = "8:00 AM - 11:00 AM"

class SettingUpdate(BaseModel):
    """Schema for updating shop parameters from the Optimization Settings page."""
    wash_only_price: Optional[float] = None
    dry_only_price: Optional[float] = None
    full_service_price: Optional[float] = None
    electricity_rate: Optional[float] = None
    water_rate: Optional[float] = None
    detergent_cost_per_load: Optional[float] = None
    off_peak_hours: Optional[str] = None

class SettingResponse(SettingBase):
    """Response schema for the frontend to sync global pricing."""
    shop_id: int
    model_config = ConfigDict(from_attributes=True)

# --- MACHINE SCHEMAS ---

class MachineBase(BaseModel):
    machine_type: str
    machine_number: int
    status: str = "Available"
    shop_id: int = 1 
    
    # Telemetry for utility cost tracking used in calculation logic
    accumulated_detergent: float = 0.0   
    accumulated_electricity: float = 0.0  
    accumulated_water: float = 0.0         

class MachineCreate(MachineBase):
    """Used for initial hardware registration in the hub."""
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
    
    # Financial performance metrics for the Monitoring Hub
    profitability_rate: float = 0.0 
    net_profit_accumulated: float = 0.0 
    
    # Holds calculated utility costs (electricity_cost, water_cost, etc.)
    metrics: Optional[Dict[str, float]] = None 

    model_config = ConfigDict(from_attributes=True)

class MachineNested(BaseModel):
    """Simplified machine view used inside Booking responses for UI labels."""
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
    Values should be cross-referenced with the current SettingsResponse on the frontend.
    """
    customer_name: str
    service_type: str
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

    booking_timestamp: Optional[datetime] = Field(default=None)

    model_config = ConfigDict(populate_by_name=True)

class BookingStatusUpdate(BaseModel):
    """Used to move transactions through the lifecycle (e.g., Ready -> Claimed)."""
    status: str

class BookingResponse(BaseModel):
    """Full response schema for the Service Terminal."""
    id: int
    customer_name: str
    service_type: str
    category: str
    weight: float
    loads: int
    total_price: float
    status: str
    booking_mode: str
    
    booking_timestamp: Optional[datetime] = None
    created_at: datetime
    
    shop_id: int 
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None
    
    washer: Optional[MachineNested] = None
    dryer: Optional[MachineNested] = None

    washer_number: Optional[int] = None
    dryer_number: Optional[int] = None

    @field_validator("washer_number", mode="before")
    @classmethod
    def get_washer_no(cls, v, info):
        if info.data.get("washer"):
            return info.data["washer"].machine_number
        return v

    @field_validator("dryer_number", mode="before")
    @classmethod
    def get_dryer_no(cls, v, info):
        if info.data.get("dryer"):
            return info.data["dryer"].machine_number
        return v

    model_config = ConfigDict(from_attributes=True)

# --- DASHBOARD & ANALYTICS SCHEMAS ---

class DashboardStats(BaseModel):
    """High-level metrics for the Owner's Overview dashboard."""
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