from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime

# --- AUTHENTICATION & OWNER SCHEMAS ---

class OwnerCreate(BaseModel):
    """Schema for initial shop owner registration and shop creation."""
    shop_name: str
    address: str
    email: EmailStr
    password: str

class UserLogin(BaseModel):
    """Schema for user authentication requests."""
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    """Profile data returned after successful login or session validation."""
    email: str
    role: str
    shop_id: Optional[int] = None
    shop_name: Optional[str] = None
    address: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, exclude_none=True)

class LoginResponse(BaseModel):
    """Standardized OAuth2-compatible login response."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

# --- SETTINGS SCHEMAS ---

class SettingBase(BaseModel):
    """
    Base settings schema containing pricing and operational rates.
    Hardcoded defaults are removed to ensure the system fetches live Database data.
    """
    full_service_price: float 
    regular_wash_price: float 
    titan_wash_price: float
    comforter_price: float
    
    electricity_rate: float
    water_rate: float
    detergent_cost_per_load: float
    
    off_peak_hours: str = "8:00 AM - 11:00 AM"

class SettingUpdate(BaseModel):
    """Schema for updating shop parameters from the Optimization Settings page."""
    full_service_price: Optional[float] = None
    regular_wash_price: Optional[float] = None
    titan_wash_price: Optional[float] = None
    comforter_price: Optional[float] = None
    
    electricity_rate: Optional[float] = None
    water_rate: Optional[float] = None
    detergent_cost_per_load: Optional[float] = None
    off_peak_hours: Optional[str] = None

class SettingResponse(SettingBase):
    """Full response schema for syncing global pricing across all frontend modals."""
    shop_id: int
    model_config = ConfigDict(from_attributes=True)

# --- INVENTORY SCHEMAS ---

class InventoryItemBase(BaseModel):
    """Base schema for laundry supply tracking and stock levels."""
    item_name: str
    category: str = "General"
    current_stock: float
    reorder_point: float
    unit: str
    # usage_rate is required for automated stock deduction during bookings
    usage_rate: float = 0.05

class InventoryItemCreate(InventoryItemBase):
    """Schema for adding new inventory items."""
    shop_id: int

class InventoryItemUpdate(BaseModel):
    """Schema for updating stock levels."""
    current_stock: Optional[float] = None
    reorder_point: Optional[float] = None
    usage_rate: Optional[float] = None
    category: Optional[str] = None

class InventoryItemResponse(InventoryItemBase):
    """Full response schema for the Inventory Dashboard."""
    id: int
    shop_id: int
    model_config = ConfigDict(from_attributes=True)

# --- INVENTORY ANALYTICS SCHEMAS ---

class InventoryUsageData(BaseModel):
    """Single data point for usage graph."""
    date: str
    usage: float

class InventoryAnalyticsResponse(BaseModel):
    """Graph data for inventory consumption trends."""
    item_id: int
    item_name: str
    unit: str
    current_stock: float
    reorder_point: float
    usage_history: List[InventoryUsageData]
    model_config = ConfigDict(from_attributes=True)

class LowStockAlert(BaseModel):
    """Alert for inventory items below reorder point."""
    id: int
    item_name: str
    current_stock: float
    reorder_point: float
    unit: str
    status: str  # "CRITICAL", "LOW", "OK"
    model_config = ConfigDict(from_attributes=True)

class InventoryDashboardStats(BaseModel):
    """Overall inventory statistics for dashboard summary."""
    total_items: int
    items_ok: int
    items_low: int
    items_critical: int
    total_stock_value: float
    low_stock_alerts: List[LowStockAlert]
    model_config = ConfigDict(from_attributes=True)

# --- MACHINE SCHEMAS ---

class MachineBase(BaseModel):
    """Base hardware schema representing Washers and Dryers."""
    machine_type: str
    machine_number: int
    status: str = "Available"
    shop_id: int = 1 
    
    accumulated_detergent: float = 0.0   
    accumulated_electricity: float = 0.0  
    accumulated_water: float = 0.0        

class MachineCreate(MachineBase):
    """Used for initial hardware registration."""
    pass 

class MachineUpdate(BaseModel):
    """Schema for updating hardware state or maintenance overrides."""
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
    """Full hardware state returned to the Machine Hub UI."""
    id: int
    total_cycles: int
    remaining_time: int
    
    current_service_type: Optional[str] = "None"
    current_price: float = 0.0
    
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
    """Schema for creating a laundry transaction."""
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
    inventory_item_id: Optional[int] = None
    inventory_quantity_used: Optional[float] = None

    add_detergent: bool = False
    add_delivery: bool = False
    is_rush: bool = False

    booking_timestamp: Optional[datetime] = Field(default=None)

    model_config = ConfigDict(populate_by_name=True)

class BookingStatusUpdate(BaseModel):
    """Transitions a booking through lifecycle states."""
    status: str

class BookingResponse(BaseModel):
    """Detailed transaction response for the Service Terminal UI."""
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
    inventory_item_id: Optional[int] = None
    inventory_item_name: Optional[str] = None
    
    washer: Optional[MachineNested] = None
    dryer: Optional[MachineNested] = None

    washer_number: Optional[int] = None
    dryer_number: Optional[int] = None

    @field_validator("washer_number", mode="before")
    @classmethod
    def get_washer_no(cls, v, info):
        if info.data.get("washer"):
            return info.data["washer"].machine_number if hasattr(info.data["washer"], 'machine_number') else None
        return v

    @field_validator("dryer_number", mode="before")
    @classmethod
    def get_dryer_no(cls, v, info):
        if info.data.get("dryer"):
            return info.data["dryer"].machine_number if hasattr(info.data["dryer"], 'machine_number') else None
        return v

    model_config = ConfigDict(from_attributes=True)

# --- DASHBOARD & ANALYTICS SCHEMAS ---

class DashboardStats(BaseModel):
    """High-level metrics for the Owner Overview analytics dashboard."""
    total_revenue: float
    revenue_trend: str
    utilization_rate: float
    utilization_trend: str
    avg_income: float
    income_trend: str
    pending_bookings: int
    bookings_trend: str
    
    full_service: int
    regular_wash: int
    titan_wash: int
    comforter: int
    
    total_weight: float
    
    forecast_data: List[Dict[str, Any]]
    optimization: Optional[Dict[str, str]] = None

class InsightResponse(BaseModel):
    """
    Schema for real-time Operational Insights (Decision Support System).
    Maps directly to the React 'Operational Insight' card.
    """
    hasIssue: bool
    type: str
    problemMessage: str
    impactDetail: str
    suggestions: List[str]

    model_config = ConfigDict(from_attributes=True)