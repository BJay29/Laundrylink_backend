from app.database import Base
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Numeric
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

class Shop(Base):
    """
    Represents a laundry business entity.
    Acts as the parent container for machines, users, and transactions.
    """
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True, index=True)
    shop_name = Column(String, unique=True, nullable=False)
    address = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Cascade deletion ensures that if a shop is removed, all related data is purged.
    users = relationship("User", back_populates="shop", cascade="all, delete-orphan")
    machines = relationship("Machine", back_populates="shop", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="shop", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "shop_name": self.shop_name,
            "address": self.address,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class User(Base):
    """
    Identity management for Owners and Staff members with RBAC.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False) 
    role = Column(String, nullable=False) # 'owner' or 'staff'
    
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

class Machine(Base):
    """
    Hardware units tracking operational state and financial performance.
    Updated to store accumulated utility costs based on real-time usage.
    """
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)
    machine_type = Column(String, nullable=False) # 'Washer' or 'Dryer'
    machine_number = Column(Integer, nullable=False)
    
    # Real-time Telemetry for Monitoring Hub
    status = Column(String, default="Available") # 'Available', 'Busy', 'Maintenance'
    current_service_type = Column(String, default="None")
    current_price = Column(Float, default=0.0)
    
    # Persistent countdown timer for frontend synchronization
    remaining_time = Column(Integer, default=0) 
    
    # Operational Analytics
    total_cycles = Column(Integer, default=0)
    net_profit_accumulated = Column(Float, default=0.0)
    # Using Numeric for precision in profitability calculations
    profitability_rate = Column(Float, default=0.0) 
    
    # ACCUMULATED COSTS: Values increase per cycle based on Naga City rates.
    # Electricity is the dominant cost for the 5000W Dryer setup.
    accumulated_electricity = Column(Float, default=0.0) 
    accumulated_water = Column(Float, default=0.0)       
    accumulated_detergent = Column(Float, default=0.0)   
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    shop = relationship("Shop", back_populates="machines")

    # Transaction History Relationships
    washer_bookings = relationship(
        "Booking", 
        foreign_keys="[Booking.washer_id]", 
        back_populates="washer"
    )
    dryer_bookings = relationship(
        "Booking", 
        foreign_keys="[Booking.dryer_id]", 
        back_populates="dryer"
    )

    def to_dict(self):
        # Calculate total overhead for the frontend optimization logic
        overhead = (self.accumulated_electricity or 0) + \
                   (self.accumulated_water or 0) + \
                   (self.accumulated_detergent or 0)
        
        return {
            "id": self.id,
            "machine_type": self.machine_type,
            "machine_number": self.machine_number,
            "status": self.status,
            "current_service_type": self.current_service_type,
            "current_price": self.current_price,
            "remaining_time": self.remaining_time,
            "total_cycles": self.total_cycles,
            "net_profit": round(self.net_profit_accumulated, 2), # Simplified name for UI
            "profitability_rate": round(self.profitability_rate, 2),
            "metrics": {
                "electricity_cost": round(self.accumulated_electricity or 0, 2),
                "water_cost": round(self.accumulated_water or 0, 2),
                "detergent_cost": round(self.accumulated_detergent or 0, 2),
                "total_overhead": round(overhead, 2)
            },
            "shop_id": self.shop_id
        }

class Booking(Base):
    """
    Laundry transactions linking customers to specific hardware units.
    Stores duration-specific data to calculate precise utility consumption.
    """
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, nullable=False)
    
    # Service Logic
    service_type = Column(String, nullable=False) 
    category = Column(String, nullable=False)
    weight = Column(Float, nullable=False)
    loads = Column(Integer, default=1)
    
    total_price = Column(Float, nullable=False)
    booking_mode = Column(String, nullable=False)
    
    # Service Duration in minutes (Used for Utility Logic calculations)
    service_duration = Column(Integer, default=45) 
    
    # Add-on modifiers
    add_detergent = Column(Boolean, default=False)
    add_delivery = Column(Boolean, default=False)
    is_rush = Column(Boolean, default=False)

    # Lifecycle: 'Pending', 'In Progress', 'Ready', 'Claimed'
    status = Column(String, default="Pending") 
    
    # Hardware Assignments (Foreign Keys)
    washer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    dryer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    shop = relationship("Shop", back_populates="bookings")
    
    # 'joined' loading prevents the 500 Network Error by fetching machine info 
    # in the same query as the booking.
    washer = relationship(
        "Machine", 
        foreign_keys=[washer_id], 
        back_populates="washer_bookings",
        lazy="joined" 
    )
    dryer = relationship(
        "Machine", 
        foreign_keys=[dryer_id], 
        back_populates="dryer_bookings",
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
            "total_price": self.total_price,
            "booking_mode": self.booking_mode,
            "status": self.status,
            "service_duration": self.service_duration,
            "washer_id": self.washer_id,
            "dryer_id": self.dryer_id,
            # Null-safe checks to prevent 500 errors when machines aren't assigned yet
            "washer_number": self.washer.machine_number if self.washer else None,
            "dryer_number": self.dryer.machine_number if self.dryer else None,
            "shop_id": self.shop_id,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }