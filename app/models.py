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

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    is_published = Column(Boolean, default=True, nullable=False)

    has_delivery = Column(Boolean, default=False, nullable=False)
    delivery_fee = Column(Float, default=0.0, nullable=False)

    is_online = Column(Boolean, default=False, nullable=False, server_default="false")

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    users = relationship("User", back_populates="shop", cascade="all, delete-orphan")
    machines = relationship("Machine", back_populates="shop", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="shop", cascade="all, delete-orphan")
    inventory = relationship("InventoryItem", back_populates="shop", cascade="all, delete-orphan")
    settings = relationship("Setting", back_populates="shop", uselist=False, cascade="all, delete-orphan")
    service_types = relationship("ServiceType", back_populates="shop", cascade="all, delete-orphan")
    add_ons = relationship("AddOn", back_populates="shop", cascade="all, delete-orphan")
    promo_codes = relationship("PromoCode", back_populates="shop", cascade="all, delete-orphan")
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
    Dynamic, per-shop service catalog.
    """
    __tablename__ = "service_types"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False, default=0.0)
    is_active = Column(Boolean, default=True)
    duration_minutes = Column(Integer, nullable=False, default=45)

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
    Per-shop na listahan ng optional add-ons.
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
    Per-shop na promo/discount codes.
    """
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String, nullable=False, index=True)
    discount_type = Column(String, nullable=False, default="percent")
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
    """
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    
    electricity_rate = Column(Float, default=12.0)
    water_rate = Column(Float, default=50.0)
    supplies_cost_per_load = Column(Float, default=10.0)

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
            "supplies_cost_per_load": self.supplies_cost_per_load,
            "minimum_weight_kg": self.minimum_weight_kg,
            "off_peak_hours": self.off_peak_hours,
            "operation_start_hour": self.operation_start_hour,
            "shop_id": self.shop_id
        }


class User(Base):
    """
    Identity management for Owners and Staff members with Role-Based Access Control (RBAC).

    UPDATED (Supabase Auth migration): TINANGGAL ang hashed_password —
    ang Supabase Auth na ang humahawak ng password storage/verification.
    IDINAGDAG ang supabase_uid — link papunta sa Supabase's
    auth.users.id, sini-sync via ang /webhooks/supabase-auth endpoint
    (see webhook_controller.py) pagkatapos ma-verify ng owner/staff ang
    kanilang email/OTP. Ang integer id (PK) ay NANATILING PAREHO —
    hindi ito ginalaw dahil dito naka-anchor ang shop_id at ibang
    relationships; ang supabase_uid ay hiwalay/karagdagang column lang.

    Nullable ang supabase_uid habang transition period pa
    (existing accounts na wala pang Supabase counterpart).
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    role = Column(String, nullable=False)
    full_name = Column(String, nullable=True)

    # NEW — Supabase auth.users.id (UUID string). Unique dahil isa lang
    # dapat na local User ang naka-tapat sa bawat Supabase identity.
    supabase_uid = Column(String(36), unique=True, index=True, nullable=True)

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

    UPDATED (Supabase Auth migration): TINANGGAL ang hashed_password,
    verification_code, at verification_expires_at — ang Supabase Auth
    na ang humahawak ng password storage AT ng OTP email verification
    (papalit sa dating sariling verification_code flow). IDINAGDAG ang
    supabase_uid — parehong dahilan/pattern ng User.supabase_uid sa
    itaas. is_verified ay NANATILI — ito pa rin ang gagamitin ng buong
    app (booking creation checks, atbp.), sini-sync na lang ngayon
    mula sa Supabase's email_confirmed_at sa halip na sa dating sariling
    verification_code flow.
    """
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    mobile_number = Column(String, nullable=False)

    # NEW — Supabase auth.users.id (UUID string).
    supabase_uid = Column(String(36), unique=True, index=True, nullable=True)

    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    notifications = relationship("Notification", back_populates="customer", cascade="all, delete-orphan")
    addresses = relationship("Address", back_populates="customer", cascade="all, delete-orphan")
    notifications_enabled = Column(Boolean, default=True, nullable=False, server_default="true")

    def to_dict(self):
        return {
            "id": self.id,
            "full_name": self.full_name,
            "email": self.email,
            "mobile_number": self.mobile_number,
            "is_active": self.is_active,
            "is_verified": self.is_verified,
            "notifications_enabled": self.notifications_enabled,
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

    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)

    source = Column(String, default="terminal", nullable=False)

    special_instructions = Column(String, nullable=True)

    fulfillment_mode = Column(String, default="dropoff", nullable=False)

    pickup_datetime = Column(DateTime(timezone=True), nullable=True)

    delivery_datetime = Column(DateTime(timezone=True), nullable=True)

    delivery_fee_charged = Column(Float, default=0.0)

    promo_code = Column(String, nullable=True)
    discount_amount = Column(Float, default=0.0)

    decline_reason = Column(String, nullable=True)

    booking_timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

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
    add_ons_used = relationship(
        "BookingAddOnUsage",
        back_populates="booking",
        cascade="all, delete-orphan",
        lazy="joined"
    )

    @property
    def shop_name(self):
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
    Junction table: anong add-ons ginamit sa isang booking.
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
    Isang notification entry para sa isang customer.
    """
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)
    booking_id = Column(Integer, ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True)

    type = Column(String, nullable=False, default="general")
    title = Column(String, nullable=False)
    message = Column(String, nullable=False)

    is_read = Column(Boolean, default=False, nullable=False, server_default="false")

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    customer = relationship("Customer", back_populates="notifications")
    booking = relationship("Booking")

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "booking_id": self.booking_id,
            "type": self.type,
            "title": self.title,
            "message": self.message,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class ActivityLog(Base):
    """
    Talaan ng mahahalagang aksyon na ginawa ng mga User sa loob ng isang shop.
    """
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)

    actor_name = Column(String, nullable=False)
    actor_role = Column(String, nullable=False)

    description = Column(String, nullable=False)

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


class Address(Base):
    """
    Isang naka-save na address ng isang customer (mobile app).
    """
    __tablename__ = "addresses"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False)

    label = Column(String, nullable=False, default="Home")
    address_line = Column(String, nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    is_default = Column(Boolean, default=False, nullable=False, server_default="false")

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    customer = relationship("Customer", back_populates="addresses")

    def to_dict(self):
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "label": self.label,
            "address_line": self.address_line,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }