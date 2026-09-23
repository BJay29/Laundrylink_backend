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


# --- STAFF MANAGEMENT SCHEMAS ---

class StaffCreate(BaseModel):
    """
    Schema used by an OWNER to create a new staff/manager account under
    their own shop.
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


# --- CUSTOMER PROFILE EDIT SCHEMAS ---

class CustomerUpdate(BaseModel):
    """
    Schema para sa "Personal information" edit form sa Profile page.
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
    """
    Base schema for a shop-defined service.

    NOTE (reconciliation — Weighing/Finalize Pricing feature): `price`
    (kasabay ng `pricing_unit`) ANG GINAGAMIT na bilang "Shop Rate" sa
    staff weighing modal (Module B ng bagong spec) — walang bagong
    hiwalay na rate field ang idinagdag, dahil ito na mismo ang parehong
    pinagmumulan ng presyo na ginagamit sa buong existing booking flow
    (walk-in at mobile).
    """
    name: str
    price: float
    is_active: bool = True
    pricing_unit: str = "load"

    washer_duration_minutes: int = 45
    dryer_duration_minutes: int = 45

    required_phases: str = "full_service"  # "wash_only" | "dry_only" | "full_service"

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

    @field_validator("pricing_unit")
    @classmethod
    def validate_pricing_unit(cls, v):
        allowed_units = {"load", "kg", "piece"}
        if v not in allowed_units:
            raise ValueError(f"pricing_unit must be one of: {', '.join(sorted(allowed_units))}")
        return v

    @field_validator("required_phases")
    @classmethod
    def validate_required_phases(cls, v):
        allowed = {"wash_only", "dry_only", "full_service"}
        if v not in allowed:
            raise ValueError(f"required_phases must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("washer_duration_minutes", "dryer_duration_minutes")
    @classmethod
    def validate_phase_duration(cls, v):
        if v <= 0:
            raise ValueError("Duration must be greater than 0 minutes.")
        return v

class ServiceTypeCreate(ServiceTypeBase):
    """NOTE: kept for backward compatibility / potential internal use."""
    shop_id: int

class ServiceTypeUpdate(BaseModel):
    """Schema for editing an existing service. All fields optional (partial update)."""
    name: Optional[str] = None
    price: Optional[float] = None
    is_active: Optional[bool] = None
    pricing_unit: Optional[str] = None
    required_phases: Optional[str] = None
    washer_duration_minutes: Optional[int] = None
    dryer_duration_minutes: Optional[int] = None

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

    @field_validator("pricing_unit")
    @classmethod
    def validate_pricing_unit(cls, v):
        if v is not None:
            allowed_units = {"load", "kg", "piece"}
            if v not in allowed_units:
                raise ValueError(f"pricing_unit must be one of: {', '.join(sorted(allowed_units))}")
        return v

    @field_validator("required_phases")
    @classmethod
    def validate_required_phases(cls, v):
        if v is not None:
            allowed = {"wash_only", "dry_only", "full_service"}
            if v not in allowed:
                raise ValueError(f"required_phases must be one of: {', '.join(sorted(allowed))}")
        return v

    @field_validator("washer_duration_minutes", "dryer_duration_minutes")
    @classmethod
    def validate_phase_duration(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Duration must be greater than 0 minutes.")
        return v

class ServiceTypeResponse(ServiceTypeBase):
    """Full response schema for the Optimization Settings page and Booking Modal."""
    id: int
    shop_id: int
    model_config = ConfigDict(from_attributes=True)

# --- ADD-ON SCHEMAS ---

class AddOnBase(BaseModel):
    """
    Base schema for a shop-defined add-on (pre-configured catalog,
    pinipili ng customer sa mobile checkout — hiwalay sa ad-hoc
    weighing_addon_charges ng Booking, see BookingFinalizePricingRequest
    sa ibaba).
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


class PromoCodeGenerateInput(BaseModel):
    """
    Schema para sa paggawa ng bagong promo code MULA SA WEB APP.
    WALANG `code` field dito, sinasadya — ang backend na mismo
    (settings_controller.create_promo_code()) ang bahalang mag-generate
    ng random code, hindi na kailangang isipin ng shop owner.
    """
    discount_type: str = "percent"
    discount_value: float
    is_active: bool = True
    max_uses: Optional[int] = None
    expires_at: Optional[datetime] = None

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

    cycle_started_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class MachineNested(BaseModel):
    """Simplified machine view used inside Booking responses."""
    id: int
    machine_type: str
    machine_number: int
    status: str
    shop_id: int 

    model_config = ConfigDict(from_attributes=True)

# --- MACHINE ASSIGNMENT SCHEMAS (multi-machine assignment feature) ---

class MachineAssignmentInput(BaseModel):
    """
    Schema para sa pag-assign ng washers papunta sa loads ng isang
    booking (AssignMachineModal). Isang LISTAHAN ng machine ids —
    dapat eksaktong kasing-dami ng booking.loads (chinecheck ito sa
    booking_controller, hindi dito, dahil kailangan muna nating i-load
    ang booking mula sa DB para malaman ang bilang ng loads).

    Kung "dry_only" ang required_phases ng service ng booking, ito
    pa rin ang gagamitin, pero mga dryer machine ids na agad ang
    ipapasa dito (hindi washers).
    """
    machine_ids: List[int]

    @field_validator("machine_ids")
    @classmethod
    def validate_machine_ids(cls, v):
        if not v:
            raise ValueError("At least one machine must be assigned.")
        if len(v) != len(set(v)):
            raise ValueError("Duplicate machine ids are not allowed.")
        return v


class MoveLoadToDryerInput(BaseModel):
    """
    Schema para sa "Move to Dryer" action ng isang specific load —
    tinatawag PER LOAD (hindi buong booking), dahil real-time na
    pinipili ang available dryer sa mismong sandaling kailangan na
    ito (hindi paunang commitment — see BookingMachineAssignment
    docstring sa models.py para sa buong reasoning).
    """
    dryer_id: int


class MachineAssignmentResponse(BaseModel):
    """
    Isang per-load machine assignment entry — kasama sa BookingResponse
    bilang listahan (`machine_assignments`), at ginagamit din bilang
    standalone response ng assign/move-to-dryer endpoints.
    """
    id: int
    booking_id: int
    load_number: int
    phase: str  # "washing" | "drying" | "done"

    washer_id: Optional[int] = None
    washer_number: Optional[int] = None
    dryer_id: Optional[int] = None
    dryer_number: Optional[int] = None

    washing_started_at: Optional[datetime] = None
    washing_completed_at: Optional[datetime] = None
    drying_started_at: Optional[datetime] = None
    drying_completed_at: Optional[datetime] = None

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

# --- PAYMENT SCHEMAS ---

class PaymentStatusUpdate(BaseModel):
    """
    Schema para sa "Mark as Paid" action ng staff (Record Sales /
    Booking Details) AT ng "Approve" action sa PaymentVerificationModal.

    payment_method ay OPTIONAL na ngayon (dating may default na "cash").
    Dahilan: kapag "Approve" ang tinatawag para sa isang GCash/PayMaya
    booking na "pending_verification", walang dapat baguhin sa
    payment_method nito — dapat manatili itong "gcash"/"paymaya", hindi
    ma-overwrite pabalik sa "cash" default. Kaya None ang ibig sabihin
    "huwag galawin, panatilihin ang existing value ng booking".
    """
    payment_method: Optional[str] = None  # "cash", "cod", "gcash", "paymaya", o None (keep existing)

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, v):
        if v is not None:
            allowed = {"cash", "cod", "gcash", "online_qr"}
            if v not in allowed:
                raise ValueError(f"payment_method must be one of: {', '.join(sorted(allowed))}")
        return v

class PaymentStatusResponse(BaseModel):
    """
    Minimal na response kapag na-query lang ang payment info ng isang
    booking.

    UPDATED (Online Payment feature): ang payment_status field na ito
    ay maaari na ring maging "pending_verification" o "rejected"
    ngayon, hindi lang "unpaid"/"paid" — plain `str` type pa rin
    (walang enum), kaya walang binago sa field definition mismo.
    """
    booking_id: int
    payment_method: Optional[str] = None
    payment_status: str
    paid_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# NEW (Online Payment feature) — Schema para sa "Reject" action ng
# staff sa isang online payment proof (PaymentVerificationModal).
# Parehong validation pattern ng BookingDeclineRequest sa ibaba.
class PaymentRejectRequest(BaseModel):
    """Schema for rejecting a customer-submitted GCash/PayMaya payment proof."""
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("A rejection reason is required.")
        if len(cleaned) > 300:
            raise ValueError("Rejection reason must be 300 characters or fewer.")
        return cleaned

class BookingSubmitPaymentProofRequest(BaseModel):
    """
    Schema para sa Module C ng mobile app — pag-attach ng proof of
    payment sa isang EXISTING booking na "Awaiting Payment" na (na-
    finalize na ng staff ang presyo, online ang payment method). Ang
    larawan mismo ay hiwalay na na-upload via POST /uploads/payment-proof
    — yung resulting public URL na lang ang ipinapasa dito.
    """
    proof_of_payment_url: str

    @field_validator("proof_of_payment_url")
    @classmethod
    def validate_url(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("proof_of_payment_url cannot be empty.")
        return cleaned


# --- WEIGHING / FINALIZE PRICING SCHEMAS (NEW — reconciled mula sa
#     Admin Dashboard spec, Module B: "Mobile Booking Notification &
#     Pricing Modal") ---

class BookingFinalizePricingRequest(BaseModel):
    """
    Schema para sa staff weighing/pricing modal — tinatawag kapag
    tini-timbang ng staff ang aktwal na dami ng laundry ng isang mobile
    booking na "Awaiting Weighing", tapos i-finalize ang presyo bago ito
    pumunta sa "Pending" (cash/cod) o "Awaiting Payment" (gcash/paymaya).

    Ang computation (ginagawa sa backend, HINDI dito — booking_controller.
    finalize_booking_pricing()):
        final_price = (final_weight × ServiceType.price) + addon_charges

    NOTE: `final_weight` dito ay laging ipinapalagay na "quantity" sa
    kahulugan ng ServiceType.pricing_unit ng booking (kg, load, o piece)
    — parehong pattern ng CustomerBookingCreate.quantity sa ibaba,
    "weight" lang ang pangalan dahil ito ang pinakakaraniwang unit sa
    laundry weighing.
    """
    final_weight: float
    addon_charges: float = 0.0

    @field_validator("final_weight")
    @classmethod
    def validate_final_weight(cls, v):
        if v <= 0:
            raise ValueError("Actual weight must be greater than 0.")
        return v

    @field_validator("addon_charges")
    @classmethod
    def validate_addon_charges(cls, v):
        if v < 0:
            raise ValueError("Add-ons/extra charges cannot be negative.")
        return v


# --- UPLOAD SCHEMAS (Supabase Storage) ---

class UploadResponse(BaseModel):
    """
    Simple response para sa /uploads/* endpoints (payment proof at shop
    QR code uploads via Supabase Storage) — public URL lang ang laman,
    na siyang ipapasa ng frontend papunta sa ibang endpoint na
    kailangan ng URL string (proof_of_payment_url, gcash_qr_url, atbp.)
    sa halip na raw file.
    """
    url: str


# --- RIDER ASSIGNMENT SCHEMAS (NEW — Pickup & Delivery feature) ---
#
# Manual-entry lang, walang Rider table/model. Dalawang HIWALAY na
# schema instance ang ginagamit (isa para sa pickup leg, isa para sa
# delivery leg — see assign_pickup_rider()/assign_delivery_rider() sa
# booking_controller.py) pero magkapareho ang shape, kaya isang schema
# lang ang kailangan.

class RiderAssignmentInput(BaseModel):
    """
    Schema para sa pag-assign ng rider (pickup o delivery leg) sa
    Service Terminal — staff mismo ang nagta-type ng pangalan at
    contact number, walang naka-catalog na listahan ng riders.
    """
    rider_name: str
    rider_contact: str

    @field_validator("rider_name")
    @classmethod
    def validate_rider_name(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Rider name cannot be empty.")
        return cleaned

    @field_validator("rider_contact")
    @classmethod
    def validate_rider_contact(cls, v):
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Rider contact number cannot be empty.")
        return cleaned


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

    payment_method: Optional[str] = "cash"

    proof_of_payment_url: Optional[str] = None

    promo_code: Optional[str] = None

    booking_timestamp: Optional[datetime] = Field(default=None)

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, v):
        if v is not None:
            allowed = {"cash", "cod", "gcash", "paymaya"}
            if v not in allowed:
                raise ValueError(f"payment_method must be one of: {', '.join(sorted(allowed))}")
        return v


class BookingAssignMachine(BaseModel):
    """
    LEGACY (multi-machine assignment feature) — dating ginagamit para
    sa pag-assign ng 1 washer + 1 dryer nang sabay. Pinapalitan na ito
    ng MachineAssignmentInput (N washers, list) + MoveLoadToDryerInput
    (per-load dryer, hiwalay na hakbang). Iniwan muna dito, hindi pa
    tinatanggal, hanggang ma-confirm nating wala nang gumagamit dito
    sa booking_controller.py/booking_routes.py pagkatapos ng update.
    """
    washer_id: Optional[int] = None
    dryer_id: Optional[int] = None

    model_config = ConfigDict(populate_by_name=True)


class BookingStatusUpdate(BaseModel):
    """
    Transitions a booking through lifecycle states.

    NOTE (Weighing feature): kasama na rin dito ang mga bagong VALUES na
    "Awaiting Weighing" at "Awaiting Payment" — plain `str` pa rin,
    walang bagong validation dinagdag (parehong existing "loose string"
    pattern ng field na ito).
    """
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

    payment_method: Optional[str] = "cash"
    payment_status: str = "unpaid"
    paid_at: Optional[datetime] = None

    proof_of_payment_url: Optional[str] = None
    payment_rejection_reason: Optional[str] = None

    # NEW (Weighing / Finalize Pricing feature)
    estimated_weight: Optional[float] = None
    estimated_price: Optional[float] = None
    final_weight: Optional[float] = None
    final_price: Optional[float] = None
    weighing_addon_charges: Optional[float] = 0.0
    weighed_at: Optional[datetime] = None

    # NEW (Order Tracking / Live Stepper feature) — backs the mobile
    # app's vertical timeline/stepper (kasama ang created_at at
    # weighed_at sa itaas para sa "Received" at "Weighed" steps).
    started_at: Optional[datetime] = None
    ready_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    estimated_completion_time: Optional[datetime] = None

    # NEW (Rider Assignment feature — Pickup & Delivery). Laging null
    # para sa "dropoff" bookings — applicable lang kapag
    # fulfillment_mode == "delivery". Ginagamit ng mobile app stepper
    # para ipakita ang "Rider on the way" step kasama ang pangalan at
    # contact number ng naka-assign na rider.
    pickup_rider_name: Optional[str] = None
    pickup_rider_contact: Optional[str] = None
    pickup_rider_assigned_at: Optional[datetime] = None
    delivery_rider_name: Optional[str] = None
    delivery_rider_contact: Optional[str] = None
    delivery_rider_assigned_at: Optional[datetime] = None

    # NEW (Delivery Address feature) — snapshot ng saved address na
    # pinili ng customer sa checkout (see Booking docstring sa models.py
    # para sa buong paliwanag). Laging null para sa "dropoff" bookings.
    delivery_address_id: Optional[int] = None
    delivery_address_line: Optional[str] = None
    delivery_latitude: Optional[float] = None
    delivery_longitude: Optional[float] = None

    inventory_items_used: List[BookingInventoryUsageResponse] = []
    add_ons_used: List[BookingAddOnUsageResponse] = []
    
    washer: Optional[MachineNested] = None
    dryer: Optional[MachineNested] = None

    washer_number: Optional[int] = None
    dryer_number: Optional[int] = None

    machine_assignments: List[MachineAssignmentResponse] = []

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
    Schema para sa booking na ginawa mismo ng customer sa mobile app.

    NOTE (Weighing feature): ang `quantity` dito ay ang ESTIMATE ng
    customer (slider/counter sa checkout) — hindi pa ito ang final.
    Sa booking_controller.create_customer_booking(), ise-save ito
    bilang Booking.estimated_weight at Booking.estimated_price (kasabay
    ng dating logic na nagko-compute ng total_price bilang paunang
    estimate), at ang bagong booking ay magsisimula sa status na
    "Awaiting Weighing" sa halip na deretsong "Awaiting Approval" kung
    saan-saan man iyon dating dinaraanan — tinatanggal ang manual
    Accept/Decline gate para sa flow na ito, dahil ang weighing/
    finalize-pricing step mismo ang bagong "confirmation point" ng shop.
    """
    shop_id: int
    service_type: str
    quantity: float
    special_instructions: Optional[str] = None
    fulfillment_mode: str = "dropoff"
    pickup_datetime: Optional[datetime] = None
    add_on_ids: List[int] = []
    promo_code: Optional[str] = None

    # NEW (Delivery Address feature) — dapat isa sa mga saved Address ng
    # customer (validated sa booking_controller.create_customer_booking()
    # na parehong customer_id at kabilang doon). Required kapag
    # fulfillment_mode == "delivery" (see validator sa ibaba); ignored
    # kapag "dropoff".
    address_id: Optional[int] = None

    payment_method: str = "cash"

    proof_of_payment_url: Optional[str] = None

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

    @field_validator("address_id")
    @classmethod
    def validate_address_required_for_delivery(cls, v, info):
        if info.data.get("fulfillment_mode") == "delivery" and v is None:
            raise ValueError("address_id is required when fulfillment_mode is 'delivery'.")
        return v

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, v):
        allowed = {"cash", "cod", "gcash", "online_qr"}
        if v not in allowed:
            raise ValueError(f"payment_method must be one of: {', '.join(sorted(allowed))}")
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

    gcash_qr_url: Optional[str] = None
    paymaya_qr_url: Optional[str] = None
    # FIXED: dating `Optional[srt]` (typo) — NameError sa pag-import ng
    # schemas.py na pumipigil sa pagsisimula ng buong backend.
    qr_code_url: Optional[str] = None

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

    gcash_qr_url: Optional[str] = None
    paymaya_qr_url: Optional[str] = None
    qr_code_url: Optional[str] = None 

    # FIXED (Payment Methods feature): dati WALA ang tatlong field na
    # ito, kaya tahimik na inaalis ng Pydantic ang accepts_* na
    # ipinapadala ng Optimization Settings — hindi na-se-save ang
    # "Payment Methods" toggles. Partial update (lahat Optional, None
    # ang ibig sabihin "huwag galawin").
    accepts_cash: Optional[bool] = None
    accepts_cod: Optional[bool] = None
    accepts_online: Optional[bool] = None

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


class ShopProfileResponse(BaseModel):
    """Schema for returning the current shop profile data."""
    shop_name: str
    address: str
    email: str
    has_delivery: bool = False
    delivery_fee: float = 0.0
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    gcash_qr_url: Optional[str] = None
    paymaya_qr_url: Optional[str] = None

    # FIXED (Payment Methods feature): dati WALA ang tatlong field na
    # ito, kaya hindi bumabalik sa frontend ang naka-save na payment
    # method flags — laging nagre-revert sa OFF ang "Online Payment"
    # toggle pagkatapos ng refresh/navigation.
    accepts_cash: bool = True
    accepts_cod: bool = False
    accepts_online: bool = False

    model_config = ConfigDict(from_attributes=True)


# --- SUPABASE WEBHOOK SCHEMAS ---

class SupabaseAuthRecord(BaseModel):
    """
    Subset ng auth.users columns na kailangan natin mula sa Supabase
    Database Webhook payload.
    """
    id: uuid_lib.UUID
    email: EmailStr
    email_confirmed_at: Optional[datetime] = None
    raw_user_meta_data: Optional[Dict[str, Any]] = None


class SupabaseWebhookPayload(BaseModel):
    """
    Standard shape ng Supabase Database Webhook payload
    (POST /webhooks/supabase-auth).
    """
    type: str
    table: str
    schema_name: str = Field(alias="schema")
    record: SupabaseAuthRecord
    old_record: Optional[SupabaseAuthRecord] = None

    model_config = ConfigDict(populate_by_name=True)