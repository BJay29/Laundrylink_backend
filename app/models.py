from app.database import Base
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

class Shop(Base):
    """
    Represents a laundry business entity.
    Acts as the parent container for machines, users, transactions, and settings.
    """
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True, index=True)
    shop_name = Column(String, unique=True, nullable=False)
    address = Column(String, nullable=True)

    # GPS coordinates for the "nearby shops" feature on the mobile app.
    # Nullable dahil NULL muna ang existing shops hanggang ma-set ng owner.
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Controls kung lalabas ang shop na ito sa public/customer-facing
    # listing (mobile app). Default True para hindi mawala ang existing
    # registered shops sa listahan.
    is_published = Column(Boolean, default=True, nullable=False)

    # NEW — kung meron bang delivery service ang shop, at magkano ang
    # bayad kung meron. Kontrolado ng shop owner sa Optimization Settings.
    has_delivery = Column(Boolean, default=False, nullable=False)
    delivery_fee = Column(Float, default=0.0, nullable=False)

    # NEW — real-time na "online" status ng shop, ibinabase sa kung may
    # aktibong WebSocket connection ba ang Service Terminal nito
    # (see app/services/ws_manager.py). True kapag may kahit isang
    # naka-bukas na Service Terminal tab/device; False kapag naubos na
    # ang lahat ng connections. Ginagamit ng mobile app para i-disable
    # ang "Book Now" button at magpakita ng "Currently Closed" label
    # kapag walang tumatanggap ng booking sa kasalukuyan.
    #
    # server_default="false" (bukod sa Python-side default=False) para
    # sigurong may valid na value ang EXISTING rows pagkatapos ng
    # migration (ALTER TABLE ... ADD COLUMN), hindi lang bagong rows.
    is_online = Column(Boolean, default=False, nullable=False, server_default="false")

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    users = relationship("User", back_populates="shop", cascade="all, delete-orphan")
    machines = relationship("Machine", back_populates="shop", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="shop", cascade="all, delete-orphan")
    inventory = relationship("InventoryItem", back_populates="shop", cascade="all, delete-orphan")
    settings = relationship("Setting", back_populates="shop", uselist=False, cascade="all, delete-orphan")
    service_types = relationship("ServiceType", back_populates="shop", cascade="all, delete-orphan")
    # NEW — per-shop add-ons and promo codes.
    add_ons = relationship("AddOn", back_populates="shop", cascade="all, delete-orphan")
    promo_codes = relationship("PromoCode", back_populates="shop", cascade="all, delete-orphan")
    # Activity trail for this shop; each entry attributes an action
    # to a specific User (via actor_name/actor_role snapshot, see below).
    activity_logs = relationship("ActivityLog", back_populates="shop", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "shop_name": self.shop_name,
            "address": self.address,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "is_published": self.is_published,
            "has_delivery": self.has_delivery,
            "delivery_fee": self.delivery_fee,
            "is_online": self.is_online,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class InventoryItem(Base):
    """
    Tracks stock levels of laundry consumables with predictive reorder points.
    """
    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)
    item_name = Column(String, index=True, nullable=False)
    category = Column(String, default="General")
    current_stock = Column(Float, default=0.0)
    reorder_point = Column(Float, default=5.0)
    unit = Column(String, default="kg")
    usage_rate = Column(Float, default=0.05) 
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    shop = relationship("Shop", back_populates="inventory")
    logs = relationship("InventoryLog", back_populates="item", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "item_name": self.item_name,
            "category": self.category,
            "current_stock": self.current_stock,
            "reorder_point": self.reorder_point,
            "unit": self.unit,
            "usage_rate": self.usage_rate,
            "shop_id": self.shop_id
        }

class InventoryLog(Base):
    """
    Records historical inventory usage data for trend visualization and graphs.
    """
    __tablename__ = "inventory_logs"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("inventory.id"), nullable=False)
    quantity_used = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    
    item = relationship("InventoryItem", back_populates="logs")

class BookingInventoryUsage(Base):
    """
    Junction table na nag-uugnay ng isang Booking sa MARAMING InventoryItem
    na ginamit dito (hal. detergent + fabric conditioner sa iisang booking).
    """
    __tablename__ = "booking_inventory_usage"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    inventory_item_id = Column(Integer, ForeignKey("inventory.id"), nullable=False)
    quantity_used = Column(Float, nullable=False)

    booking = relationship("Booking", back_populates="inventory_usages")
    inventory_item = relationship("InventoryItem")

    def to_dict(self):
        return {
            "id": self.id,
            "inventory_item_id": self.inventory_item_id,
            "item_name": self.inventory_item.item_name if self.inventory_item else None,
            "quantity_used": self.quantity_used,
            "unit": self.inventory_item.unit if self.inventory_item else None,
        }

class ServiceType(Base):
    """
    Dynamic, per-shop service catalog. Replaces the old fixed pricing columns
    on Setting. A shop owner defines their own services and prices here from
    the Optimization Settings page, and these records are what populate the
    'Service Type' dropdown in the Create Booking modal.

    Added duration_minutes so the shop owner also configures how long each
    service actually runs on a machine. This drives machine.remaining_time
    for any booking that references a configured service.

    Added pricing_unit so bawat service ay may sariling paraan ng
    pagpepresyo — may per load (Regular Wash), may per kg (Wash, Dry, and
    Fold), may per piece (Comforter). Ito ang nagpapakita sa Optimization
    Settings at sa customer-facing mobile app kung "₱65 / load" o
    "₱15 / kg" ang display.

    New shops intentionally start with ZERO service types — the owner must
    configure at least one before bookings referencing that service can be
    created.
    """
    __tablename__ = "service_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    is_active = Column(Boolean, default=True)
    duration_minutes = Column(Integer, nullable=False, default=45)

    # "load", "kg", o "piece". Default "load" dahil 'yun ang dating
    # implicit assumption bago dumagdag ang concept na ito.
    pricing_unit = Column(String(20), nullable=False, default="load")

    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    shop = relationship("Shop", back_populates="service_types")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "price": self.price,
            "is_active": self.is_active,
            "duration_minutes": self.duration_minutes,
            "pricing_unit": self.pricing_unit,
            "shop_id": self.shop_id
        }

class AddOn(Base):
    """
    NEW — Per-shop na listahan ng optional add-ons (fabric softener
    upgrade, rush service, atbp.) na pwedeng idagdag ng customer sa
    isang booking. Kagaya ng ServiceType, shop-defined ito — nagsisimula
    sa ZERO add-ons ang bawat bagong shop.
    """
    __tablename__ = "add_ons"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    is_active = Column(Boolean, default=True)

    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    shop = relationship("Shop", back_populates="add_ons")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "price": self.price,
            "is_active": self.is_active,
            "shop_id": self.shop_id
        }


class PromoCode(Base):
    """
    NEW — Per-shop na promo/discount codes. discount_type ay "percent"
    (hal. 10 = 10% off) o "fixed" (hal. 50 = ₱50 off). max_uses ay
    optional na limit sa dami ng beses magagamit ito (null = walang
    limit); times_used ay nagta-track kung ilang beses nagamit na.
    """
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, index=True)
    discount_type = Column(String, nullable=False, default="percent")  # "percent" o "fixed"
    discount_value = Column(Float, nullable=False, default=0.0)
    is_active = Column(Boolean, default=True)
    max_uses = Column(Integer, nullable=True)
    times_used = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)

    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    shop = relationship("Shop", back_populates="promo_codes")

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "discount_type": self.discount_type,
            "discount_value": self.discount_value,
            "is_active": self.is_active,
            "max_uses": self.max_uses,
            "times_used": self.times_used,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "shop_id": self.shop_id
        }

class Setting(Base):
    """
    Global configuration for operational unit costs and booking rules.
    Service-specific pricing has moved to the ServiceType table.
    """
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    
    electricity_rate = Column(Float, default=12.0)
    water_rate = Column(Float, default=50.0)
    detergent_cost_per_load = Column(Float, default=10.0)

    minimum_weight_kg = Column(Float, default=6.0)
    
    off_peak_hours = Column(String, default="8:00 AM - 11:00 AM")
    operation_start_hour = Column(Integer, default=8)
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    shop = relationship("Shop", back_populates="settings")

    def to_dict(self):
        return {
            "id": self.id,
            "electricity_rate": self.electricity_rate,
            "water_rate": self.water_rate,
            "detergent_cost_per_load": self.detergent_cost_per_load,
            "minimum_weight_kg": self.minimum_weight_kg,
            "off_peak_hours": self.off_peak_hours,
            "operation_start_hour": self.operation_start_hour,
            "shop_id": self.shop_id
        }

class User(Base):
    """
    Identity management for Owners and Staff members with Role-Based Access Control (RBAC).

    Added full_name. Dating wala nito kahit meron nang full_name field
    ang StaffCreate schema — hindi pa ito naisa-save kahit saan, kaya
    laging email lang ang lumalabas sa Activity Log bilang actor (hal.
    "juan@gmail.com" imbes na "Juan Dela Cruz"). Ngayon, kapag gumagawa
    ng owner o staff account, kasama na ang tunay na pangalan. Nullable
    dahil sa mga EXISTING accounts na wala pang laman dito (na-create
    bago idagdag ang column na ito) — kailangang mag-fallback sa email
    sa mga lugar na gumagamit nito.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    shop = relationship("Shop", back_populates="users")

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
            "shop_id": self.shop_id,
            "is_active": self.is_active
        }

class Customer(Base):
    """
    Identity management for mobile app customers (laundry service bookers).
    """
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    mobile_number = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)

    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    verification_code = Column(String, nullable=True)
    verification_expires_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # NEW — isang customer ay pwedeng magkaroon ng maraming notification
    # entries (isa per booking-status event — see Notification class sa
    # ibaba). cascade="all, delete-orphan" para awtomatikong malinis din
    # ang mga notification kung matanggal man ang customer account.
    notifications = relationship("Notification", back_populates="customer", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "mobile_number": self.mobile_number,
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class Machine(Base):
    """
    Hardware units (Washers/Dryers) tracking real-time status and financial performance.
    """
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)
    machine_type = Column(String, nullable=False)
    machine_number = Column(Integer, nullable=False)
    
    status = Column(String, default="Available") 
    current_service_type = Column(String, default="None")
    current_price = Column(Float, default=0.0)
    remaining_time = Column(Integer, default=0) 
    total_cycles = Column(Integer, default=0)
    
    net_profit_accumulated = Column(Float, default=0.0)
    profitability_rate = Column(Float, default=0.0) 
    accumulated_electricity = Column(Float, default=0.0) 
    accumulated_water = Column(Float, default=0.0) 
    accumulated_detergent = Column(Float, default=0.0) 
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    shop = relationship("Shop", back_populates="machines")

    washer_bookings = relationship("Booking", foreign_keys="[Booking.washer_id]", back_populates="washer")
    dryer_bookings = relationship("Booking", foreign_keys="[Booking.dryer_id]", back_populates="dryer")

    def to_dict(self):
        overhead = (self.accumulated_electricity or 0.0) + (self.accumulated_water or 0.0) + (self.accumulated_detergent or 0.0)
        return {
            "id": self.id,
            "machine_type": self.machine_type,
            "machine_number": self.machine_number,
            "status": self.status,
            "current_service_type": self.current_service_type,
            "current_price": self.current_price,
            "remaining_time": self.remaining_time,
            "total_cycles": self.total_cycles,
            "net_profit_accumulated": round(self.net_profit_accumulated or 0.0, 2),
            "profitability_rate": round(self.profitability_rate or 0.0, 2),
            "metrics": {
                "electricity_cost": round(self.accumulated_electricity or 0.0, 2),
                "water_cost": round(self.accumulated_water or 0.0, 2),
                "detergent_cost": round(self.accumulated_detergent or 0.0, 2),
                "total_overhead": round(overhead, 2)
            },
            "shop_id": self.shop_id
        }

class Booking(Base):
    """
    Laundry transactions linking customer service requests to hardware units.

    UPDATED: Added customer_id + source to support bookings self-created
    by a mobile-app customer (as opposed to staff-created bookings from
    the Service Terminal). A customer-sourced booking starts life with
    status "Awaiting Approval" instead of "Pending"/"In Progress" — it
    must be explicitly Accepted (→ "Pending", enters the normal flow) or
    Declined (→ "Declined", stays out of the Service Terminal but is kept
    for history) by the shop before it behaves like any other booking.

    UPDATED: Added special_instructions, fulfillment_mode, pickup_datetime,
    delivery_datetime, delivery_fee_charged, promo_code, discount_amount —
    all customer-facing booking details captured by the mobile app's
    booking flow (drop-off vs. delivery, scheduling, discounts).
    """
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, nullable=False)
    service_type = Column(String, nullable=False) 
    category = Column(String, nullable=False)
    weight = Column(Float, nullable=False)
    loads = Column(Integer, default=1)
    total_price = Column(Float, nullable=False)
    booking_mode = Column(String, nullable=False)
    service_duration = Column(Integer, default=45) 
    add_detergent = Column(Boolean, default=False)
    add_delivery = Column(Boolean, default=False)
    is_rush = Column(Boolean, default=False)
    status = Column(String, default="Pending") 
    
    washer_id = Column(Integer, ForeignKey("machines.id", ondelete="SET NULL"), nullable=True)
    dryer_id = Column(Integer, ForeignKey("machines.id", ondelete="SET NULL"), nullable=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)

    # nag-uugnay sa Customer (mobile app user) kung sino ang gumawa ng
    # booking na ito. Nullable dahil ang mga bookings na ginawa via
    # Service Terminal (staff/manual) ay walang customer.
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)

    # "terminal" (staff-created, default) o "mobile" (customer
    # self-booked via app). Ginagamit para malaman kung saan galing
    # ang booking nang hindi na kailangang mag-infer mula sa customer_id.
    source = Column(String, default="terminal", nullable=False)

    # NEW — libreng text note mula sa customer (hal. "huwag i-bleach").
    special_instructions = Column(String, nullable=True)

    # NEW — "dropoff" (customer mismo magdadala/kukuha sa shop) o
    # "delivery" (may rider ang shop na kukuha/maghahatid).
    fulfillment_mode = Column(String, default="dropoff", nullable=False)

    # NEW — kailan kukunin ng rider ang maruming labada (delivery mode
    # lang ito, null kung dropoff).
    pickup_datetime = Column(DateTime(timezone=True), nullable=True)

    # NEW — inaasahang oras ng paghahatid pabalik ng malinis na labada
    # (delivery mode lang ito, null kung dropoff).
    delivery_datetime = Column(DateTime(timezone=True), nullable=True)

    # NEW — snapshot ng delivery fee noong oras ng booking (hindi 'yung
    # current Shop.delivery_fee — baka magbago pa 'yun mamaya).
    delivery_fee_charged = Column(Float, default=0.0)

    # NEW — snapshot ng promo code ginamit (kung meron) at ang nabawas
    # na halaga dahil dito.
    promo_code = Column(String, nullable=True)
    discount_amount = Column(Float, default=0.0)

    # NEW — dahilan ng pag-decline ng shop sa isang mobile booking request
    # (hal. "Fully booked", "Closed for the day", o custom text). Null
    # maliban kung "Declined" ang status. Makikita ito ng customer sa
    # mobile app (History/Notifications) para malaman kung bakit hindi
    # natuloy ang kanilang booking, sa halip na basta na lang "Declined"
    # na walang paliwanag.
    decline_reason = Column(String, nullable=True)

    booking_timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # NEW — eager-loaded (lazy="joined") kagaya ng washer/dryer sa ibaba.
    # Ito ang dahilan kung bakit nagawa nating gawin ang shop_name bilang
    # simpleng @property sa halip na hiwalay pang query: sigurado tayong
    # naka-load na ang shop object bago pa man i-access ang property na
    # ito, kahit sa isang listahan ng maraming bookings (GET
    # /bookings/mine, na sumasaklaw sa MARAMING shops).
    shop = relationship("Shop", back_populates="bookings", lazy="joined")
    washer = relationship("Machine", foreign_keys=[washer_id], back_populates="washer_bookings", lazy="joined")
    dryer = relationship("Machine", foreign_keys=[dryer_id], back_populates="dryer_bookings", lazy="joined")
    customer = relationship("Customer", foreign_keys=[customer_id])
    inventory_usages = relationship(
        "BookingInventoryUsage",
        back_populates="booking",
        cascade="all, delete-orphan",
        lazy="joined"
    )
    # NEW — add-ons na ginamit sa booking na ito.
    add_ons_used = relationship(
        "BookingAddOnUsage",
        back_populates="booking",
        cascade="all, delete-orphan",
        lazy="joined"
    )

    @property
    def shop_name(self):
        """
        NEW — read-only convenience property, HINDI isang DB column.
        Sinasagot nito ang gap na dating wala: ang Booking mismo ay
        walang naka-save na pangalan ng shop (shop_id lang), pero ang
        mobile app's booking history (GET /bookings/mine) ay
        sumasaklaw sa MARAMING shops sa iisang listahan — kailangan
        niyang malaman kung "aling shop" ang bawat booking nang hindi
        na kailangang mag-issue ng hiwalay na query kada item.

        Dahil BookingResponse ay gumagamit ng ConfigDict(from_attributes=
        True), awtomatikong makikita ni Pydantic ang property na ito
        (parang ordinary attribute lang mula sa pananaw nito) basta
        idagdag lang ang `shop_name` bilang field sa schema — walang
        kailangang gawing field_validator na tulad ng washer_number/
        dryer_number sa BookingResponse.
        """
        return self.shop.shop_name if self.shop else None

    def to_dict(self):
        return {
            "id": self.id,
            "customer_name": self.customer_name,
            "shop_name": self.shop_name,
            "service_type": self.service_type,
            "category": self.category,
            "weight": self.weight,
            "loads": self.loads,
            "total_price": round(self.total_price or 0.0, 2),
            "booking_mode": self.booking_mode,
            "status": self.status,
            "service_duration": self.service_duration,
            "is_rush": self.is_rush,
            "add_detergent": self.add_detergent,
            "add_delivery": self.add_delivery,
            "washer_id": self.washer_id,
            "dryer_id": self.dryer_id,
            "customer_id": self.customer_id,
            "source": self.source,
            "special_instructions": self.special_instructions,
            "fulfillment_mode": self.fulfillment_mode,
            "pickup_datetime": self.pickup_datetime.isoformat() if self.pickup_datetime else None,
            "delivery_datetime": self.delivery_datetime.isoformat() if self.delivery_datetime else None,
            "delivery_fee_charged": self.delivery_fee_charged,
            "promo_code": self.promo_code,
            "discount_amount": self.discount_amount,
            "decline_reason": self.decline_reason,
            "inventory_items_used": [u.to_dict() for u in self.inventory_usages],
            "add_ons_used": [a.to_dict() for a in self.add_ons_used],
            "washer_number": self.washer.machine_number if self.washer else None,
            "dryer_number": self.dryer.machine_number if self.dryer else None,
            "shop_id": self.shop_id,
            "booking_timestamp": self.booking_timestamp.isoformat() if self.booking_timestamp else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class BookingAddOnUsage(Base):
    """
    NEW — Junction table: anong add-ons ginamit sa isang booking.
    price_at_booking ay snapshot ng presyo noong oras ng booking, hindi
    'yung current AddOn.price — para hindi magbago ang dating booking
    kahit baguhin pa ng shop ang presyo mamaya (parehong pattern gaya
    ng BookingInventoryUsage sa itaas).
    """
    __tablename__ = "booking_addon_usage"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    add_on_id = Column(Integer, ForeignKey("add_ons.id"), nullable=False)
    price_at_booking = Column(Float, nullable=False)

    booking = relationship("Booking", back_populates="add_ons_used")
    add_on = relationship("AddOn")

    def to_dict(self):
        return {
            "id": self.id,
            "add_on_id": self.add_on_id,
            "add_on_name": self.add_on.name if self.add_on else None,
            "price_at_booking": self.price_at_booking,
        }

class Notification(Base):
    """
    NEW — Isang notification entry para sa isang customer, karaniwan ay
    nauugnay sa isang partikular na Booking status change (submitted,
    accepted, declined, in progress, ready, claimed, cancelled).

    SADYANG hiwalay ito sa "current booking status" (BookingResponse) —
    dating derive-lang ang mga "notification" sa mobile app mula sa
    kasalukuyang status ng bawat booking, kaya IISA lang ang lumalabas
    per booking (nagbabago lang ang text kapag nagbago ang status,
    hindi dumadami). Sa pag-iral ng table na ito, bawat TRANSITION
    (Awaiting Approval → Pending, Pending → In Progress, atbp.) ay
    isang HIWALAY na row — totoong history ng mga pangyayari, hindi
    isang "snapshot" lang ng pinaka-huling status.

    is_read ay nagbibigay-daan sa tunay na read/unread na UI sa mobile
    app (bell badge count = bilang ng is_read == False), sa halip na
    yung dating heuristic na ibinabase na lang sa "final" statuses.

    booking_id ay NULLABLE at ondelete="SET NULL" — kung sakaling
    matanggal ang booking (hindi dapat mangyari sa normal flow, pero
    hindi rin sinasadyang ipagbawal dito), mananatili pa rin ang
    notification record bilang history, hindi na lang naka-link sa
    isang partikular na booking.
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True)

    title = Column(String, nullable=False)      # e.g. "Booking confirmed"
    message = Column(String, nullable=False)    # e.g. "CleanWave Laundry accepted your Regular Wash booking."

    is_read = Column(Boolean, default=False, nullable=False, server_default="false")

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    customer = relationship("Customer", back_populates="notifications")
    booking = relationship("Booking")

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "booking_id": self.booking_id,
            "title": self.title,
            "message": self.message,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class ActivityLog(Base):
    """
    Talaan ng mahahalagang aksyon na ginawa ng mga User (Owner/Staff/
    Manager) sa loob ng isang shop, para sa accountability at history
    tracking.

    actor_name at actor_role ay sinadyang naka-DUPLICATE dito (hindi
    lang naka-relate sa User table) — kahit matanggal balang araw ang
    User account na gumawa nito (nag-resign, na-deactivate), permanente
    pa ring makikita sa log kung SINO at ANONG ROLE ang gumawa ng aksyon,
    imbes na mawala o maging "Unknown User" na lang.

    Walang direktang foreign key papuntang User dito nang sinasadya —
    ang shop_id + actor_name snapshot na ang sapat para sa layunin ng
    isang simpleng activity trail, at iniiwasan nito ang kailangang
    isipin pa ang ondelete behavior kung matatanggal ang User.

    FIXED: timestamp column ay ginawang DateTime(timezone=True) —
    dating walang timezone info ang naka-save (naive datetime), kaya
    kahit UTC talaga ang laman, walang "Z"/offset suffix sa isoformat()
    output, kaya inaakala ng browser na LOCAL time na ito. Sanhi ito ng
    maling oras (8-hour offset sa PH) sa Activity Log page.
    """
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)

    actor_name = Column(String, nullable=False)   # e.g. "Juan Dela Cruz"
    actor_role = Column(String, nullable=False)   # "owner", "staff", "manager"

    description = Column(String, nullable=False)  # e.g. "Created a booking for Maria - ₱250"

    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    shop = relationship("Shop", back_populates="activity_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "shop_id": self.shop_id,
            "actor_name": self.actor_name,
            "actor_role": self.actor_role,
            "description": self.description,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }