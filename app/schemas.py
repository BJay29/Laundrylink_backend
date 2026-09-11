from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid as uuid_lib

# --- AUTHENTICATION & OWNER SCHEMAS ---

class OwnerCreate(BaseModel):
    """
    Schema for shop creation, ginagamit PAGKATAPOS na-verify na ang
    Owner sa Supabase Auth (hindi na ito ang registration endpoint mismo
    — see webhook_controller.py para dun nangyayari ang pag-sync ng
    User row). Ito ay para sa hiwalay na "create my shop" step na
    tinatawag ng frontend gamit ang Supabase JWT ng bagong-verify na
    owner, para gumawa ng kanilang Shop record.

    UPDATED (Supabase Auth migration): TINANGGAL ang password field —
    hindi na ito FastAPI ang humahawak ng password, Supabase Auth na.
    """
    shop_name: str
    address: str


class UserResponse(BaseModel):
    """
    Profile data returned after successful login or session validation.
    """
    email: str
    full_name: Optional[str] = None
    role: str
    shop_id: Optional[int] = None
    shop_name: Optional[str] = None
    address: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, exclude_none=True)


# UPDATED (Supabase Auth migration): TINANGGAL ang LoginResponse — hindi
# na FastAPI ang nagbibigay ng access_token, Supabase Auth
# (signInWithPassword) na ang gumagawa nito sa frontend mismo.
# UserResponse pa rin ang gagamitin, pero ibabalik na lang ito ng isang
# simpleng "GET /me"-style endpoint na gumagamit ng
# Depends(get_current_user) sa halip na login endpoint.


# --- STAFF MANAGEMENT SCHEMAS ---

class StaffCreate(BaseModel):
    """
    Schema used by an OWNER to create a new staff/manager account under
    their own shop. shop_id is derived server-side from the currently
    logged-in Owner's JWT, never supplied by the client.

    UPDATED (Supabase Auth migration): TINANGGAL ang password field —
    ang bagong staff member mismo ang magsa-sign-up via Supabase Auth
    (email/password nila mismo), hindi na ito gagawin ng Owner
    papasok sa isang password. Ang endpoint na ito ay nagse-set na
    lang ng "invited" na record (walang supabase_uid pa) na
    ma-cclaim/ma-sync kapag nag-sign-up na ang staff gamit ang
    parehong email.
    """
    full_name: str
    email: EmailStr
    role: str = "staff"  # "staff" or "manager"

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Full name cannot be empty.")
        return cleaned

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        allowed_roles = {"staff", "manager"}
        if v not in allowed_roles:
            raise ValueError(f"role must be one of: {', '.join(sorted(allowed_roles))}")
        return v

class StaffResponse(BaseModel):
    """Profile data returned after successfully creating a staff/manager account."""
    id: int
    full_name: Optional[str] = None
    email: str
    role: str
    shop_id: Optional[int] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)

# --- CUSTOMER (MOBILE APP) SCHEMAS ---

# UPDATED (Supabase Auth migration): TINANGGAL ang CustomerCreate,
# CustomerLogin, CustomerVerifyEmail, CustomerResendCode, at
# CustomerPasswordUpdate — lahat ng ito ay hinahawakan na ng Supabase
# Auth SDK mismo sa Flutter app (signUp, signInWithPassword, verifyOTP,
# resend, at updateUser para sa password change). Walang FastAPI
# endpoint na kailangan para dito.

class CustomerResponse(BaseModel):
    """Profile data returned after successful customer login or registration."""
    id: int
    full_name: str
    email: str
    mobile_number: str
    is_active: bool
    is_verified: bool
    notifications_enabled: bool = True

    model_config = ConfigDict(from_attributes=True)


# UPDATED (Supabase Auth migration): TINANGGAL ang CustomerLoginResponse
# — hindi na FastAPI ang nagbibigay ng access_token/login response.

# --- CUSTOMER PROFILE EDIT SCHEMAS ---

class CustomerUpdate(BaseModel):
    """
    Schema para sa "Personal information" edit form sa Profile page.
    Email at password ay SINASADYANG HINDI kasama dito: password ay
    Supabase Auth SDK na ang bahala (client-side updateUser call), at
    email ay hindi pa rin muna pinapayagang baguhin.
    """
    full_name: Optional[str] = None
    mobile_number: Optional[str] = None

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v):
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Full name cannot be empty.")
            return cleaned
        return v

    @field_validator("mobile_number")
    @classmethod
    def validate_mobile_number(cls, v):
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Mobile number cannot be empty.")
            return cleaned
        return v


class CustomerNotificationSettingsUpdate(BaseModel):
    """Schema para sa notification on/off toggle sa Settings."""
    notifications_enabled: bool

# --- ADDRESS (SAVED ADDRESSES) SCHEMAS ---

class AddressBase(BaseModel):
    """
    Base schema para sa isang naka-save na address ng customer.
    """
    label: str = "Home"
    address_line: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_default: bool = False

    @field_validator("label")
    @classmethod
    def validate_label(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Label cannot be empty.")
        return cleaned

    @field_validator("address_line")
    @classmethod
    def validate_address_line(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Address cannot be empty.")
        return cleaned


class AddressCreate(AddressBase):
    """Schema para sa paggawa ng bagong saved address."""
    pass


class AddressUpdate(BaseModel):
    """Schema para sa pag-edit ng existing address. Lahat optional (partial update)."""
    label: Optional[str] = None
    address_line: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    is_default: Optional[bool] = None

    @field_validator("label")
    @classmethod
    def validate_label(cls, v):
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Label cannot be empty.")
            return cleaned
        return v

    @field_validator("address_line")
    @classmethod
    def validate_address_line(cls, v):
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Address cannot be empty.")
            return cleaned
        return v


class AddressResponse(AddressBase):
    """Full response schema para sa Saved Addresses list sa Profile page."""
    id: int
    customer_id: int
    model_config = ConfigDict(from_attributes=True)

# --- SERVICE TYPE SCHEMAS ---

class ServiceTypeBase(BaseModel):
    """Base schema for a shop-defined service."""
    name: str
    price: float
    is_active: bool = True
    duration_minutes: int = 45
    pricing_unit: str = "load"

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Service name cannot be empty.")
        return cleaned

    @field_validator("price")
    @classmethod
    def validate_price(cls, v):
        if v < 0:
            raise ValueError("Price cannot be negative.")
        return v

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, v):
        if v <= 0:
            raise ValueError("duration_minutes must be greater than 0.")
        return v

    @field_validator("pricing_unit")
    @classmethod
    def validate_pricing_unit(cls, v):
        allowed_units = {"load", "kg", "piece"}
        if v not in allowed_units:
            raise ValueError(f"pricing_unit must be one of: {', '.join(sorted(allowed_units))}")
        return v

class ServiceTypeCreate(ServiceTypeBase):
    """NOTE: kept for backward compatibility / potential internal use."""
    shop_id: int

class ServiceTypeUpdate(BaseModel):
    """Schema for editing an existing service. All fields optional (partial update)."""
    name: Optional[str] = None
    price: Optional[float] = None
    is_active: Optional[bool] = None
    duration_minutes: Optional[int] = None
    pricing_unit: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Service name cannot be empty.")
            return cleaned
        return v

    @field_validator("price")
    @classmethod
    def validate_price(cls, v):
        if v is not None and v < 0:
            raise ValueError("Price cannot be negative.")
        return v

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, v):
        if v is not None and v <= 0:
            raise ValueError("duration_minutes must be greater than 0.")
        return v

    @field_validator("pricing_unit")
    @classmethod
    def validate_pricing_unit(cls, v):
        if v is not None:
            allowed_units = {"load", "kg", "piece"}
            if v not in allowed_units:
                raise ValueError(f"pricing_unit must be one of: {', '.join(sorted(allowed_units))}")
        return v

class ServiceTypeResponse(ServiceTypeBase):
    """Full response schema for the Optimization Settings page and Booking Modal."""
    id: int
    shop_id: int
    model_config = ConfigDict(from_attributes=True)

# --- ADD-ON SCHEMAS ---

class AddOnBase(BaseModel):
    """Base schema for a shop-defined add-on."""
    name: str
    price: float
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Add-on name cannot be empty.")
        return cleaned

    @field_validator("price")
    @classmethod
    def validate_price(cls, v):
        if v < 0:
            raise ValueError("Price cannot be negative.")
        return v

class AddOnCreate(AddOnBase):
    """NOTE: shop_id kept for internal/compat use only."""
    shop_id: int

class AddOnUpdate(BaseModel):
    """Schema for editing an existing add-on. All fields optional (partial update)."""
    name: Optional[str] = None
    price: Optional[float] = None
    is_active: Optional[bool] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if v is not None:
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Add-on name cannot be empty.")
            return cleaned
        return v

    @field_validator("price")
    @classmethod
    def validate_price(cls, v):
        if v is not None and v < 0:
            raise ValueError("Price cannot be negative.")
        return v

class AddOnResponse(AddOnBase):
    """Full response schema for the Optimization Settings page (owner-facing)."""
    id: int
    shop_id: int
    model_config = ConfigDict(from_attributes=True)

class AddOnPreview(BaseModel):
    """Safe, public view ng isang add-on — para sa customer-facing mobile app."""
    id: int
    name: str
    price: float

    model_config = ConfigDict(from_attributes=True)

# --- PROMO CODE SCHEMAS ---

class PromoCodeBase(BaseModel):
    """Base schema for a shop-defined promo/discount code."""
    code: str
    discount_type: str = "percent"
    discount_value: float
    is_active: bool = True
    max_uses: Optional[int] = None
    expires_at: Optional[datetime] = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v):
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("Promo code cannot be empty.")
        return cleaned

    @field_validator("discount_type")
    @classmethod
    def validate_discount_type(cls, v):
        allowed = {"percent", "fixed"}
        if v not in allowed:
            raise ValueError(f"discount_type must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("discount_value")
    @classmethod
    def validate_discount_value(cls, v):
        if v <= 0:
            raise ValueError("discount_value must be greater than 0.")
        return v

class PromoCodeCreate(PromoCodeBase):
    """NOTE: shop_id kept for internal/compat use only."""
    shop_id: int

class PromoCodeUpdate(BaseModel):
    """Schema for editing an existing promo code. All fields optional (partial update)."""
    code: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[float] = None
    is_active: Optional[bool] = None
    max_uses: Optional[int] = None
    expires_at: Optional[datetime] = None

    @field_validator("code")
    @classmethod
    def validate_code(cls, v):
        if v is not None:
            cleaned = v.strip().upper()
            if not cleaned:
                raise ValueError("Promo code cannot be empty.")
            return cleaned
        return v

    @field_validator("discount_type")
    @classmethod
    def validate_discount_type(cls, v):
        if v is not None:
            allowed = {"percent", "fixed"}
            if v not in allowed:
                raise ValueError(f"discount_type must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("discount_value")
    @classmethod
    def validate_discount_value(cls, v):
        if v is not None and v <= 0:
            raise ValueError("discount_value must be greater than 0.")
        return v

class PromoCodeResponse(PromoCodeBase):
    """Full response schema for the Optimization Settings page (owner-facing)."""
    id: int
    shop_id: int
    times_used: int
    model_config = ConfigDict(from_attributes=True)

# --- SETTINGS SCHEMAS ---

class SettingBase(BaseModel):
    """Base settings schema containing operational rates and booking rules."""
    electricity_rate: float
    water_rate: float
    supplies_cost_per_load: float
    minimum_weight_kg: float = 6.0
    off_peak_hours: str = "8:00 AM - 11:00 AM"

class SettingUpdate(BaseModel):
    """Schema for updating shop parameters from the Optimization Settings page."""
    electricity_rate: Optional[float] = None
    water_rate: Optional[float] = None
    supplies_cost_per_load: Optional[float] = None
    minimum_weight_kg: Optional[float] = None
    off_peak_hours: Optional[str] = None

    @field_validator("minimum_weight_kg")
    @classmethod
    def validate_minimum_weight(cls, v):
        if v is not None and v <= 0:
            raise ValueError("minimum_weight_kg must be greater than 0.")
        return v

class SettingResponse(SettingBase):
    """Full response schema for syncing global operational rates across all frontend modals."""
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
    usage_rate: float = 0.05

class InventoryItemCreate(InventoryItemBase):
    """Schema for adding new inventory items."""
    shop_id: int

class InventoryItemUpdate(BaseModel):
    """Schema for updating an existing inventory item. All fields optional."""
    item_name: Optional[str] = None
    category: Optional[str] = None
    current_stock: Optional[float] = None
    reorder_point: Optional[float] = None
    usage_rate: Optional[float] = None
    unit: Optional[str] = None
    shop_id: Optional[int] = None

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

# --- BOOKING INVENTORY USAGE SCHEMAS ---

class BookingInventoryItemInput(BaseModel):
    """Isang inventory item na ginamit sa isang booking, kasama ang quantity."""
    inventory_item_id: int
    quantity_used: float

    @field_validator("quantity_used")
    @classmethod
    def validate_quantity(cls, v):
        if v <= 0:
            raise ValueError("quantity_used must be greater than 0.")
        return v

class BookingInventoryUsageResponse(BaseModel):
    """Isang item na ginamit sa booking, para sa BookingResponse."""
    id: int
    inventory_item_id: int
    item_name: Optional[str] = None
    quantity_used: float
    unit: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

# --- BOOKING ADD-ON USAGE SCHEMAS ---

class BookingAddOnUsageResponse(BaseModel):
    """Isang add-on na ginamit sa booking, para sa BookingResponse."""
    id: int
    add_on_id: int
    add_on_name: Optional[str] = None
    price_at_booking: float

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
    inventory_items: List[BookingInventoryItemInput] = []

    add_detergent: bool = False
    add_delivery: bool = False
    is_rush: bool = False

    booking_timestamp: Optional[datetime] = Field(default=None)

    model_config = ConfigDict(populate_by_name=True)


class BookingAssignMachine(BaseModel):
    """Used when assigning a machine to an existing Pending booking."""
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    model_config = ConfigDict(populate_by_name=True)


class BookingStatusUpdate(BaseModel):
    """Transitions a booking through lifecycle states."""
    status: str


class BookingDeclineRequest(BaseModel):
    """Schema for declining a customer-submitted booking request."""
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("A decline reason is required.")
        if len(cleaned) > 300:
            raise ValueError("Decline reason must be 300 characters or fewer.")
        return cleaned

class BookingResponse(BaseModel):
    """Detailed transaction response for the Service Terminal UI AND the mobile app."""
    id: int
    customer_name: str
    shop_name: Optional[str] = None

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

    customer_id: Optional[int] = None
    source: Optional[str] = "terminal"

    special_instructions: Optional[str] = None
    fulfillment_mode: Optional[str] = "dropoff"
    pickup_datetime: Optional[datetime] = None
    delivery_datetime: Optional[datetime] = None
    delivery_fee_charged: Optional[float] = 0.0
    promo_code: Optional[str] = None
    discount_amount: Optional[float] = 0.0

    decline_reason: Optional[str] = None

    inventory_items_used: List[BookingInventoryUsageResponse] = []
    add_ons_used: List[BookingAddOnUsageResponse] = []
    
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

# --- CUSTOMER (MOBILE APP) BOOKING SCHEMAS ---

class CustomerBookingCreate(BaseModel):
    """Schema para sa booking na ginawa mismo ng customer sa mobile app."""
    shop_id: int
    service_type: str
    quantity: float
    special_instructions: Optional[str] = None
    fulfillment_mode: str = "dropoff"
    pickup_datetime: Optional[datetime] = None
    add_on_ids: List[int] = []
    promo_code: Optional[str] = None

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v):
        if v <= 0:
            raise ValueError("quantity must be greater than 0.")
        return v

    @field_validator("fulfillment_mode")
    @classmethod
    def validate_fulfillment_mode(cls, v):
        allowed = {"dropoff", "delivery"}
        if v not in allowed:
            raise ValueError(f"fulfillment_mode must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("pickup_datetime")
    @classmethod
    def validate_pickup_required_for_delivery(cls, v, info):
        if info.data.get("fulfillment_mode") == "delivery" and v is None:
            raise ValueError("pickup_datetime is required when fulfillment_mode is 'delivery'.")
        return v


class BookingDecisionResponse(BaseModel):
    """Simple response para sa accept/decline endpoints."""
    message: str
    booking_id: int
    status: str

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
    """Schema for real-time Operational Insights (Decision Support System)."""
    hasIssue: bool
    type: str
    problemMessage: str
    impactDetail: str
    suggestions: List[str]

# --- ACTIVITY LOG SCHEMAS ---

class ActivityLogResponse(BaseModel):
    """Response schema for a single Activity Log entry."""
    id: int
    shop_id: int
    actor_name: str
    actor_role: str
    description: str
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)

# --- NOTIFICATION SCHEMAS ---

class NotificationResponse(BaseModel):
    """A single notification entry for the mobile app's Notifications page."""
    id: int
    booking_id: Optional[int] = None
    type: str = "general"
    title: str
    message: str
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class NotificationMarkReadResponse(BaseModel):
    """Simple confirmation response for the mark-read / mark-all-read endpoints."""
    message: str
    updated_count: int


class UnreadCountResponse(BaseModel):
    """Simple response para sa GET /notifications/unread-count."""
    unread_count: int

# --- CUSTOMER-FACING (PUBLIC) SHOP SCHEMAS ---

class ShopServicePreview(BaseModel):
    """Safe, public view ng isang service — para sa customer-facing mobile app."""
    id: int
    name: str
    price: float
    duration_minutes: int
    pricing_unit: str

    model_config = ConfigDict(from_attributes=True)


class ShopPublicResponse(BaseModel):
    """Listing view ng isang shop — ginagamit sa mobile app's Home carousel at Shop Selection Page."""
    id: int
    shop_name: str
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: Optional[float] = None

    has_delivery: bool = False
    delivery_fee: float = 0.0
    is_online: bool = False

    model_config = ConfigDict(from_attributes=True)


class ShopDetailResponse(BaseModel):
    """Shop Detail page: shop info + list ng available services + add-ons."""
    id: int
    shop_name: str
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    has_delivery: bool = False
    delivery_fee: float = 0.0
    is_online: bool = False
    services: List[ShopServicePreview] = []
    add_ons: List[AddOnPreview] = []

    model_config = ConfigDict(from_attributes=True)

# --- SETTINGS & PROFILE SCHEMAS ---

class ShopProfileUpdate(BaseModel):
    """Schema for updating the shop information."""
    shop_name: Optional[str] = None
    address: Optional[str] = None
    email: Optional[EmailStr] = None
    has_delivery: Optional[bool] = None
    delivery_fee: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator("delivery_fee")
    @classmethod
    def validate_delivery_fee(cls, v):
        if v is not None and v < 0:
            raise ValueError("delivery_fee cannot be negative.")
        return v

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, v):
        if v is not None and not (-90.0 <= v <= 90.0):
            raise ValueError("latitude must be between -90 and 90.")
        return v

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, v):
        if v is not None and not (-180.0 <= v <= 180.0):
            raise ValueError("longitude must be between -180 and 180.")
        return v


# UPDATED (Supabase Auth migration): TINANGGAL ang PasswordUpdate —
# ang password change ay Supabase Auth SDK na ang bahala
# (client-side supabase.auth.updateUser({ password: newPassword })).


class ShopProfileResponse(BaseModel):
    """Schema for returning the current shop profile data."""
    shop_name: str
    address: str
    email: str
    has_delivery: bool = False
    delivery_fee: float = 0.0
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


# --- SUPABASE WEBHOOK SCHEMAS (NEW) ---

class SupabaseAuthRecord(BaseModel):
    """
    Subset ng auth.users columns na kailangan natin mula sa Supabase
    Database Webhook payload — hindi lahat ng columns, laman lang na
    ginagamit ng sync logic (see webhook_controller.sync_verified_user).
    """
    id: uuid_lib.UUID
    email: EmailStr
    email_confirmed_at: Optional[datetime] = None
    raw_user_meta_data: Optional[Dict[str, Any]] = None


class SupabaseWebhookPayload(BaseModel):
    """
    Standard shape ng Supabase Database Webhook payload
    (POST /webhooks/supabase-auth). 'schema' ay reserved word sa
    Pydantic/Python conventions dito kaya naka-alias papuntang
    schema_name.
    """
    type: str
    table: str
    schema_name: str = Field(alias="schema")
    record: SupabaseAuthRecord
    old_record: Optional[SupabaseAuthRecord] = None

    model_config = ConfigDict(populate_by_name=True)