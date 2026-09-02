from pydantic import BaseModel, EmailStr, ConfigDict, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime

# --- AUTHENTICATION & OWNER SCHEMAS ---

class OwnerCreate(BaseModel):
    """
    Schema for initial shop owner registration and shop creation.

    Added full_name so the Owner's real name is captured at registration
    time (previously only StaffCreate had this field, so Owners
    registering their own shop had no name on file — the Activity Log
    would show their email even after full_name support was added
    elsewhere).
    """
    owner_name: str
    shop_name: str
    address: str
    email: EmailStr
    password: str

    @field_validator("owner_name")
    @classmethod
    def validate_owner_name(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Owner name cannot be empty.")
        return cleaned

class UserLogin(BaseModel):
    """Schema for user authentication requests."""
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    """
    Profile data returned after successful login or session validation.

    UPDATED: Added full_name so the frontend can display/cache the
    logged-in user's real name (e.g. for Activity Log attribution,
    greeting text, etc.) instead of falling back to email everywhere.
    """
    email: str
    full_name: Optional[str] = None
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

# --- STAFF MANAGEMENT SCHEMAS ---

class StaffCreate(BaseModel):
    """
    Schema used by an OWNER to create a new staff/manager account under
    their own shop. Unlike OwnerCreate, this does NOT create a new Shop —
    shop_id is derived server-side from the currently logged-in Owner's
    JWT (see auth_routes.py's /register/staff endpoint), never supplied
    by the client. This is what powers a shop having multiple individual
    login accounts (one per staff/manager) instead of one shared account,
    which in turn is what makes the Activity Log meaningful — each action
    can be attributed to a real person instead of a generic shared login.
    """
    full_name: str
    email: EmailStr
    password: str
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

class CustomerCreate(BaseModel):
    """Schema for customer self-registration via the mobile app."""
    full_name: str
    email: EmailStr
    mobile_number: str
    password: str

class CustomerLogin(BaseModel):
    """Schema for customer authentication requests from the mobile app."""
    email: EmailStr
    password: str

class CustomerResponse(BaseModel):
    """Profile data returned after successful customer login or registration."""
    id: int
    full_name: str
    email: str
    mobile_number: str
    is_active: bool
    is_verified: bool

    model_config = ConfigDict(from_attributes=True)

class CustomerLoginResponse(BaseModel):
    """Standardized OAuth2-compatible login response for customers."""
    access_token: str
    token_type: str = "bearer"
    customer: CustomerResponse

class CustomerVerifyEmail(BaseModel):
    """Schema for submitting the 6-digit verification code."""
    email: EmailStr
    code: str

class CustomerResendCode(BaseModel):
    """Schema for requesting a new verification code."""
    email: EmailStr

# --- SERVICE TYPE SCHEMAS ---

class ServiceTypeBase(BaseModel):
    """
    Base schema for a shop-defined service. Shop owners create these
    themselves from Optimization Settings — includes pricing AND how
    long the service runs on a machine (duration_minutes), which drives
    the Machine Monitoring card's remaining_time.

    Added pricing_unit — bawat service ay may sariling unit ng presyo
    ("load", "kg", o "piece"), dahil hindi pareho lahat ng service ng
    isang shop (hal. Regular Wash = per load, Wash&Fold = per kg).
    """
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
    """
    NOTE: kept for backward compatibility / potential internal use, but
    setting_routes.py's POST /settings/services endpoint now uses
    ServiceTypeBase directly (no shop_id field) since shop_id is derived
    from the JWT via Depends(get_current_user), not supplied by the client.
    """
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

# --- ADD-ON SCHEMAS (NEW) ---

class AddOnBase(BaseModel):
    """
    Base schema for a shop-defined add-on (fabric softener upgrade, rush
    service, atbp.) — kagaya ng ServiceType pattern, shop owner ang
    gumagawa nito sa Optimization Settings.
    """
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
    """NOTE: shop_id kept for internal/compat use only — see ServiceTypeCreate note above."""
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

# --- PROMO CODE SCHEMAS (NEW) ---

class PromoCodeBase(BaseModel):
    """
    Base schema for a shop-defined promo/discount code. discount_type ay
    "percent" (10 = 10% off) o "fixed" (50 = ₱50 off). max_uses ay
    optional na limit (null = walang limit).
    """
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
    """NOTE: shop_id kept for internal/compat use only — see ServiceTypeCreate note above."""
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
    """
    Base settings schema containing operational rates and booking rules.
    Service-specific pricing has moved to ServiceType — this now only
    covers costs/rules that apply shop-wide regardless of service.
    """
    electricity_rate: float
    water_rate: float
    detergent_cost_per_load: float

    # Minimum billable weight (in KG) enforced on the Create Booking modal.
    # Defaults to 6kg but is configurable per shop from Optimization Settings.
    minimum_weight_kg: float = 6.0

    off_peak_hours: str = "8:00 AM - 11:00 AM"

class SettingUpdate(BaseModel):
    """Schema for updating shop parameters from the Optimization Settings page."""
    electricity_rate: Optional[float] = None
    water_rate: Optional[float] = None
    detergent_cost_per_load: Optional[float] = None

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
    """
    Isang inventory item na ginamit sa isang booking, kasama ang quantity.
    Listahan nito ang mapupunta sa BookingCreate.inventory_items —
    pinapayagan nitong maraming consumables (detergent, fabcon, atbp.)
    sa iisang booking, bawat isa may sariling quantity.
    """
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

# --- BOOKING ADD-ON USAGE SCHEMAS (NEW) ---

class BookingAddOnUsageResponse(BaseModel):
    """Isang add-on na ginamit sa booking, para sa BookingResponse."""
    id: int
    add_on_id: int
    add_on_name: Optional[str] = None
    price_at_booking: float

    model_config = ConfigDict(from_attributes=True)

# --- BOOKING SCHEMAS ---

class BookingCreate(BaseModel):
    """
    Schema for creating a laundry transaction.
    washer_id and dryer_id are fully optional — if both are None,
    the backend will set the booking status to 'Pending'.
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
    # Listahan ng maraming consumables (hal. detergent + fabric conditioner)
    # na ginamit sa isang booking. Optional — pwedeng walang laman kung
    # walang consumable na ginamit (hal. walk-in na may sariling sabon).
    inventory_items: List[BookingInventoryItemInput] = []

    add_detergent: bool = False
    add_delivery: bool = False
    is_rush: bool = False

    booking_timestamp: Optional[datetime] = Field(default=None)

    model_config = ConfigDict(populate_by_name=True)


class BookingAssignMachine(BaseModel):
    """
    Used when assigning a machine to an existing Pending booking
    from the Service Terminal. At least one of washer_id or dryer_id
    must be provided (validated in the controller).
    """
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

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

    # Nagsasabi kung saan galing ang booking (mobile customer vs.
    # staff/Service Terminal) at kung sinong customer, kung meron.
    customer_id: Optional[int] = None
    source: Optional[str] = "terminal"

    # NEW — special instructions, delivery/dropoff scheduling, at
    # pricing breakdown (delivery fee, promo discount).
    special_instructions: Optional[str] = None
    fulfillment_mode: Optional[str] = "dropoff"
    pickup_datetime: Optional[datetime] = None
    delivery_datetime: Optional[datetime] = None
    delivery_fee_charged: Optional[float] = 0.0
    promo_code: Optional[str] = None
    discount_amount: Optional[float] = 0.0

    # Listahan ng lahat ng items/add-ons na ginamit sa booking na ito.
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
    """
    Schema para sa booking na ginawa mismo ng customer sa mobile app —
    mas simple kaysa BookingCreate (walang machine assignment, walang
    customer_name dahil galing na sa JWT).

    quantity ay generic na number lang — ang ibig sabihin nito
    (load/kg/piece) ay depende sa pricing_unit ng napiling service.

    fulfillment_mode: "dropoff" (customer mismo magdadala/kukuha sa
    shop) o "delivery" (may rider ang shop). "delivery" ay bawal lang
    piliin kung ang shop ay walang Shop.has_delivery = True (che-check
    ito sa controller, hindi dito, dahil kailangan pang i-query ang
    shop). pickup_datetime ay REQUIRED lang kapag "delivery" ang mode.
    """
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
    """
    Schema for real-time Operational Insights (Decision Support System).
    Maps directly to the React 'Operational Insight' card.
    """
    hasIssue: bool
    type: str
    problemMessage: str
    impactDetail: str
    suggestions: List[str]

# --- ACTIVITY LOG SCHEMAS ---

class ActivityLogResponse(BaseModel):
    """
    Response schema for a single Activity Log entry. actor_name and
    actor_role are stored redundantly on the ActivityLog row itself
    (not just looked up via a relationship) so history remains readable
    even if the acting User account is later deleted.
    """
    id: int
    shop_id: int
    actor_name: str
    actor_role: str
    description: str
    timestamp: datetime

    model_config = ConfigDict(from_attributes=True)

# --- CUSTOMER-FACING (PUBLIC) SHOP SCHEMAS ---

class ShopServicePreview(BaseModel):
    """
    Safe, public view ng isang service — para sa customer-facing mobile
    app. Walang internal cost breakdown (electricity/water/detergent
    costs), 'yun ang dahilan kung bakit hiwalay ito sa ServiceTypeResponse.
    """
    id: int
    name: str
    price: float
    duration_minutes: int
    pricing_unit: str

    model_config = ConfigDict(from_attributes=True)


class ShopPublicResponse(BaseModel):
    """
    Listing view ng isang shop — ginagamit sa mobile app's Home carousel
    at Shop Selection Page. Walang financial/internal data, safe i-expose
    nang walang auth.
    """
    id: int
    shop_name: str
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: Optional[float] = None  # populated lang ng GET /shops/nearby

    # NEW — para makita agad sa listing/carousel kung may delivery
    # ang shop na ito, kahit hindi pa binubuksan ang Shop Detail.
    has_delivery: bool = False
    delivery_fee: float = 0.0

    # NEW — real-time na "online" status, ibinabase sa aktibong
    # WebSocket connection ng Service Terminal (see Shop.is_online sa
    # models.py). Ginagamit ng Home carousel / Shop Selection Page para
    # magpakita ng "Currently Closed" badge at i-disable ang "Book Now"
    # kung walang tumatanggap ng booking sa kasalukuyan. Default False
    # para safe (offline) muna hanggang ma-confirm ang aktwal na status
    # mula sa DB.
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
    # NEW — see ShopPublicResponse.is_online note above. Ito ang
    # ginagamit ng Shop Detail page para i-disable ang "Book Now" button
    # at magpakita ng "Currently Closed" / "Offline" label.
    is_online: bool = False
    services: List[ShopServicePreview] = []
    add_ons: List[AddOnPreview] = []

    model_config = ConfigDict(from_attributes=True)

# --- SETTINGS & PROFILE SCHEMAS ---

class ShopProfileUpdate(BaseModel):
    """
    Schema for updating the shop information.

    UPDATED: Added has_delivery + delivery_fee — parehong Shop model
    fields, kaya same update_shop_profile() controller function ang
    humahawak nito (walang bagong controller function na kailangan).
    """
    shop_name: Optional[str] = None
    address: Optional[str] = None
    email: Optional[EmailStr] = None
    has_delivery: Optional[bool] = None
    delivery_fee: Optional[float] = None

    @field_validator("delivery_fee")
    @classmethod
    def validate_delivery_fee(cls, v):
        if v is not None and v < 0:
            raise ValueError("delivery_fee cannot be negative.")
        return v

class PasswordUpdate(BaseModel):
    """Schema for validating password change requests."""
    old_password: str
    new_password: str

class ShopProfileResponse(BaseModel):
    """Schema for returning the current shop profile data."""
    shop_name: str
    address: str
    email: str
    has_delivery: bool = False
    delivery_fee: float = 0.0

    model_config = ConfigDict(from_attributes=True)