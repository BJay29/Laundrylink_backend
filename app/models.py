from app.database import Base
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

class Shop(Base):
    """
    Represents a laundry business entity. 
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

class User(Base):
    """
    Central Authentication table.
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

class Machine(Base):
    """
    Hardware units. Status field drives colors in Dashboard and Machine Hub.
    """
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)
    machine_type = Column(String, nullable=False) # 'Washer' or 'Dryer'
    machine_number = Column(Integer, nullable=False)
    
    status = Column(String, default="Available") # 'Available', 'Busy', 'Maintenance'
    
    total_cycles = Column(Integer, default=0)
    avg_detergent = Column(Float, default=0.0)
    avg_electricity = Column(Float, default=0.0)
    avg_water = Column(Float, default=0.0)
    remaining_time = Column(Integer, default=0) 
    
    shop_id = Column(Integer, ForeignKey("shops.id"))

    shop = relationship("Shop", back_populates="machines")

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

class Booking(Base):
    """
    Laundry transactions. References Machine IDs for automation.
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
    
    add_detergent = Column(Boolean, default=False)
    add_delivery = Column(Boolean, default=False)
    is_rush = Column(Boolean, default=False)

    status = Column(String, default="Pending") # 'Pending', 'In Progress', 'Ready', 'Claimed'
    
    washer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    dryer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    
    shop_id = Column(Integer, ForeignKey("shops.id"))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    shop = relationship("Shop", back_populates="bookings")
    
    # RELATIONSHIP FIX:
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