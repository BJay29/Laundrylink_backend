from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, List
from datetime import datetime

# --- REGISTRATION SCHEMAS ---

class OwnerCreate(BaseModel):
    """
    Schema for internal/backend registration of Shop Owners.
    Used via Thunder Client to populate the initial database.
    """
    shop_name: str
    address: str
    email: EmailStr
    password: str

# --- AUTHENTICATION SCHEMAS ---

class UserLogin(BaseModel):
    """ 
    Standard login credentials for both Web and Mobile.
    Authenticates against the PostgreSQL users table.
    """
    email: EmailStr
    password: str

# --- MACHINE SCHEMAS ---

class MachineBase(BaseModel):
    """
    Base attributes for hardware units.
    Matches the 'Live Status' requirement for the monitoring grid.
    """
    machine_type: str # 'Washer' or 'Dryer'
    machine_number: int
    status: str = "Available" # 'Available', 'Busy', 'Maintenance'

class MachineCreate(MachineBase):
    """
    Used for onboarding new hardware into a specific shop.
    """
    shop_id: int

class MachineUpdate(BaseModel):
    """
    Schema used for toggling maintenance or manual timer overrides.
    """
    status: Optional[str] = None
    remaining_time: Optional[int] = None

class MachineResponse(MachineBase):
    """
    Full machine telemetry for the Machine Hub table.
    Includes performance metrics and real-time countdown data.
    """
    id: int
    shop_id: int
    total_cycles: int
    avg_detergent: float
    avg_electricity: float
    avg_water: float
    remaining_time: int

    model_config = ConfigDict(from_attributes=True)

# --- BOOKING SCHEMAS (Matches BookingModal.jsx) ---

class BookingCreate(BaseModel):
    """
    Validation for new laundry transactions from the frontend.
    Handles the machine assignment IDs required for the status-sync logic.
    """
    customer_name: str
    service_type: str
    category: str
    weight: float
    loads: int
    total_price: float
    booking_mode: str # 'smart' or 'manual'
    
    # Linked hardware IDs to trigger 'Busy' status in backend
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None
    
    # Feature Toggles
    add_detergent: bool = False
    add_delivery: bool = False
    is_rush: bool = False

class BookingResponse(BaseModel):
    """
    Detailed order data for the Service Terminal and Dashboard.
    Provides nested machine info for clear UI status labeling.
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
    created_at: datetime
    
    # Assigned IDs
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

# --- DATA REPRESENTATION (RESPONSE) SCHEMAS ---

class UserResponse(BaseModel):
    """ 
    Standard user profile returned upon successful authentication.
    Supplies the shop_id used as a global filter for all frontend requests.
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