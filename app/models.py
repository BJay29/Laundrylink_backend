from app.database import Base
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

class Shop(Base):
    """
    Represents a laundry business entity. 
    One shop can have multiple users, machines, and bookings.
    """
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True, index=True)
    shop_name = Column(String, unique=True, nullable=False)
    address = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
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
    Central Authentication table for Owners and Staff.
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
    Hardware units. Stores cumulative usage metrics updated after every booking.
    Calculations are based on service duration (e.g., Full Service vs Regular Wash).
    """
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)
    machine_type = Column(String, nullable=False) # 'Washer' or 'Dryer'
    machine_number = Column(Integer, nullable=False)
    
    # Status drives UI colors (Available=Green, Busy=Blue, Maintenance=Red)
    status = Column(String, default="Available") 
    
    # Usage metrics - Total number of times the machine has been used
    total_cycles = Column(Integer, default=0)
    
    # CUMULATIVE CONSUMPTION DATA (Historical totals, not per-cycle)
    # These values persist and increase with every transaction
    total_electricity_cost = Column(Float, default=0.0) # Accumulated PHP/kWh cost
    total_water_cost = Column(Float, default=0.0)       # Accumulated PHP/Liters cost
    total_detergent_cost = Column(Float, default=0.0)   # Accumulated PHP/ml cost
    
    remaining_time = Column(Integer, default=0) 
    
    # Mandatory relationship to Shop
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True)

    shop = relationship("Shop", back_populates="machines")

    # Tracking which bookings are assigned to this hardware
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
        return {
            "id": self.id,
            "machine_type": self.machine_type,
            "machine_number": self.machine_number,
            "status": self.status,
            "total_cycles": self.total_cycles,
            "total_electricity": round(self.total_electricity_cost, 2),
            "total_water": round(self.total_water_cost, 2),
            "total_detergent": round(self.total_detergent_cost, 2),
            "remaining_time": self.remaining_time,
            "shop_id": self.shop_id or 1
        }

class Booking(Base):
    """
    Laundry transactions. Connects customers to specific hardware units.
    Cost logic: 
    - Regular/Titan Wash: ~38-48 mins
    - Full Service: ~78 mins (Wash + Dry)
    - Comforter: ~95 mins (Titan Wash + Extra Dry)
    """
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, nullable=False)
    
    service_type = Column(String, nullable=False) # 'Regular Wash', 'Titan Wash', 'Full Service', 'Comforter'
    category = Column(String, nullable=False)     # 'Clothes', 'Linens', etc.
    weight = Column(Float, nullable=False)
    loads = Column(Integer, default=1)
    
    total_price = Column(Float, nullable=False)
    booking_mode = Column(String, nullable=False) # 'Self Service' or 'Full Service'
    
    # Optional add-ons
    add_detergent = Column(Boolean, default=False)
    add_delivery = Column(Boolean, default=False)
    is_rush = Column(Boolean, default=False)

    status = Column(String, default="Pending") # 'Pending', 'In Progress', 'Ready', 'Claimed'
    
    # Foreign keys linking to specific Machine IDs
    washer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    dryer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    shop = relationship("Shop", back_populates="bookings")
    
    # Joined loading ensures machine data is available when fetching bookings
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
            "washer_id": self.washer_id,
            "dryer_id": self.dryer_id,
            "shop_id": self.shop_id or 1,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }