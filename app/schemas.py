from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, List
from datetime import datetime

# --- REGISTRATION SCHEMAS ---

class OwnerCreate(BaseModel):
    """
    Schema for internal/backend registration of Shop Owners.
    Used via tools like Thunder Client to populate the initial database.
    """
    shop_name: str
    address: str
    email: EmailStr
    password: str

# --- AUTHENTICATION SCHEMAS ---

class UserLogin(BaseModel):
    """ 
    Standard login credentials for both Web and Mobile platforms.
    Authenticates users against the PostgreSQL users table.
    """
    email: EmailStr
    password: str

# --- MACHINE SCHEMAS ---

class MachineBase(BaseModel):
    """
    Base attributes for hardware units (Washers/Dryers).
    Matches the 'Live Status' requirements for the monitoring grid.
    """
    machine_type: str # 'Washer' or 'Dryer'
    machine_number: int
    status: str = "Available" # Options: 'Available', 'Busy', 'Maintenance'

class MachineCreate(MachineBase):
    """
    Schema used for onboarding new hardware into a specific laundry shop.
    """
    shop_id: int

class MachineUpdate(BaseModel):
    """
    Used for toggling maintenance status or manual timer overrides.
    """
    status: Optional[str] = None
    remaining_time: Optional[int] = None

class MachineMiniResponse(BaseModel):
    """
    Reduced machine data for nested responses in the Service Terminal.
    Provides essential info (e.g., machine_number) for UI labeling.
    """
    id: int
    machine_type: str
    machine_number: int

    model_config = ConfigDict(from_attributes=True)

class MachineResponse(MachineBase):
    """
    Full machine telemetry for the Machine Hub table.
    Includes performance metrics and real-time countdown data for the UI.
    """
    id: int
    shop_id: int
    total_cycles: int
    avg_detergent: float
    avg_electricity: float
    avg_water: float
    remaining_time: int

    model_config = ConfigDict(from_attributes=True)

# --- BOOKING SCHEMAS ---

class BookingCreate(BaseModel):
    """
    Validation for new laundry transactions initiated from the frontend.
    Handles machine assignment IDs required for backend status synchronization.
    """
    customer_name: str
    service_type: str
    category: str
    weight: float
    loads: int
    total_price: float
    booking_mode: str # 'smart' or 'manual'
    
    # Linked hardware IDs to trigger 'Busy' status in the backend
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None
    
    # Feature Toggles for additional services
    add_detergent: bool = False
    add_delivery: bool = False
    is_rush: bool = False

class BookingResponse(BaseModel):
    """
    Detailed order data for the Service Terminal and Dashboard.
    Supports nested machine objects to replace 'Pending' with actual machine numbers.
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
    created_at: datetime # Used to display the exact booking time in the UI
    
    # Assigned IDs returned for reference
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    # Nested Machine Data (Populated by SQLAlchemy relationships)
    # Critical for displaying "W1" or "D1" in the Service Terminal table
    washer: Optional[MachineMiniResponse] = None
    dryer: Optional[MachineMiniResponse] = None

    model_config = ConfigDict(from_attributes=True)

class StatusUpdate(BaseModel):
    """
    Simplified schema for updating order status throughout its lifecycle.
    Example: Moving a booking from 'In Progress' to 'Ready'.
    """
    status: str

# --- DATA REPRESENTATION (RESPONSE) SCHEMAS ---

class UserResponse(BaseModel):
    """ 
    Standard user profile returned upon successful authentication.
    Provides the shop_id used as a global filter for multi-tenant data.
    """
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
    """
    The final payload for React/Flutter login handlers.
    Includes the JWT Bearer token and user/shop context.
    """
    access_token: str
    token_type: str = "bearer"
    user: UserResponse