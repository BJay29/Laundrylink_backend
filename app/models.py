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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    users = relationship("User", back_populates="shop", cascade="all, delete-orphan")
    machines = relationship("Machine", back_populates="shop", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="shop", cascade="all, delete-orphan")
    inventory = relationship("InventoryItem", back_populates="shop", cascade="all, delete-orphan")
    settings = relationship("Setting", back_populates="shop", uselist=False, cascade="all, delete-orphan")
    service_types = relationship("ServiceType", back_populates="shop", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "shop_name": self.shop_name,
            "address": self.address,
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

    UPDATED: Added duration_minutes so the shop owner also configures how
    long each service actually runs on a machine. This replaces the
    hardcoded/estimated runtime in PredictionService.get_machine_runtime()
    for any booking that references a configured service — the Machine
    Monitoring card now reflects the shop's own configured duration.

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

    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    shop = relationship("Shop", back_populates="service_types")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "price": self.price,
            "is_active": self.is_active,
            "duration_minutes": self.duration_minutes,
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
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    shop = relationship("Shop", back_populates="users")

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
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
    
    booking_timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    shop = relationship("Shop", back_populates="bookings")
    washer = relationship("Machine", foreign_keys=[washer_id], back_populates="washer_bookings", lazy="joined")
    dryer = relationship("Machine", foreign_keys=[dryer_id], back_populates="dryer_bookings", lazy="joined")
    inventory_usages = relationship(
        "BookingInventoryUsage",
        back_populates="booking",
        cascade="all, delete-orphan",
        lazy="joined"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "customer_name": self.customer_name,
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
            "inventory_items_used": [u.to_dict() for u in self.inventory_usages],
            "washer_number": self.washer.machine_number if self.washer else None,
            "dryer_number": self.dryer.machine_number if self.dryer else None,
            "shop_id": self.shop_id,
            "booking_timestamp": self.booking_timestamp.isoformat() if self.booking_timestamp else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }