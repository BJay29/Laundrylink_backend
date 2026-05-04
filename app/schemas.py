from pydantic import BaseModel, EmailStr, ConfigDict
from typing import Optional, List
from datetime import datetime

# --- REGISTRATION SCHEMAS ---

class OwnerCreate(BaseModel):
    """
    Schema for internal/backend registration of Shop Owners.
    Used via Thunder Client to populate the database without a frontend form.
    """
    shop_name: str
    address: str
    email: EmailStr
    password: str

# --- AUTHENTICATION SCHEMAS ---

class UserLogin(BaseModel):
    """ 
    Standard login credentials for both Web and Mobile.
    Used to authenticate Owners and Staff against the PostgreSQL database.
    """
    email: EmailStr
    password: str

# --- MACHINE SCHEMAS (For Machine Hub & Monitoring) ---

class MachineBase(BaseModel):
    """
    Base attributes for laundry units.
    Matches the 'Live Status' requirement for the monitoring grid.
    """
    machine_type: str # 'Washer' or 'Dryer'
    machine_number: int
    status: str = "Available" # 'Available', 'Busy', 'Maintenance'

class MachineCreate(MachineBase):
    """
    Schema for creating new laundry units in the database.
    Links the machine to a specific shop.
    """
    shop_id: int

class MachineUpdate(BaseModel):
    """
    Schema used specifically for updating machine status or toggling maintenance.
    """
    status: Optional[str] = None
    remaining_time: Optional[int] = None

class MachineResponse(MachineBase):
    """
    Full machine data including operational metrics for the Machine Hub table.
    Matches the columns: Machine ID, Type, Status, Cycles Run, and Avg Costs.
    """
    id: int
    shop_id: int
    total_cycles: int
    
    # Cost Metrics per Figma Design (image_a84f44.png)
    avg_detergent: float
    avg_electricity: float
    avg_water: float
    
    # Real-time data for Monitoring Grid
    remaining_time: int

    model_config = ConfigDict(from_attributes=True)

# --- BOOKING SCHEMAS (Matches BookingModal.jsx) ---

class BookingCreate(BaseModel):
    """
    Schema to validate new orders from the React frontend.
    Handles both Smart and Manual mode inputs.
    """
    customer_name: str
    service_type: str
    category: str
    weight: float
    loads: int
    total_price: float
    booking_mode: str # 'smart' or 'manual'
    
    # Machine Assignments
    # These link to the Machine table primary keys to trigger status updates
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None
    
    # Add-on Toggles
    add_detergent: bool = False
    add_delivery: bool = False
    is_rush: bool = False

class BookingResponse(BaseModel):
    """
    Schema for displaying orders in the Service Terminal.
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
    
    # Assigned hardware details
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

# --- DATA REPRESENTATION (RESPONSE) SCHEMAS ---

class UserResponse(BaseModel):
    """ 
    Simplified user response focused on shop identification.
    Returns the essential data needed for the React dashboard context.
    """
    email: str
    role: str
    
    # Shop-specific details required for frontend persistence
    shop_id: Optional[int] = None
    shop_name: Optional[str] = None
    address: Optional[str] = None

    model_config = ConfigDict(
        from_attributes=True,
        exclude_none=True 
    )

class LoginResponse(BaseModel):
    """
    The final JSON structure sent to the React and Flutter frontends.
    Contains the bearer token and the simplified user/shop object.
    """
    access_token: str
    token_type: str = "bearer"
    user: UserResponse