from app.database import Base
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

class Shop(Base):
    """
    Represents a laundry business entity. 
    Stores business-wide data like the shop name and its physical location.
    Used for multi-tenant data isolation across the platform.
    """
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True, index=True)
    shop_name = Column(String, unique=True, nullable=False)
    address = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    # Cascade delete ensures that removing a shop cleans up all associated data
    users = relationship("User", back_populates="shop", cascade="all, delete-orphan")
    machines = relationship("Machine", back_populates="shop", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="shop", cascade="all, delete-orphan")

class User(Base):
    """
    Central Authentication table for the Laundry System. 
    Stores login credentials and access levels for Owners and Staff.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False) 
    role = Column(String, nullable=False) # Roles: 'owner' or 'staff'
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    shop = relationship("Shop", back_populates="users")

class Machine(Base):
    """
    Represents hardware units (Washers/Dryers).
    The 'status' field drives the color-coding in the Real-time Monitoring Grid
    and the availability logic in the Booking Controller.
    """
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)
    machine_type = Column(String, nullable=False) # Options: 'Washer' or 'Dryer'
    machine_number = Column(Integer, nullable=False) # Visual ID: e.g., 1, 2, 3
    
    # Live Status: 'Available', 'Busy', 'Maintenance'
    status = Column(String, default="Available")
    
    # Performance Metrics for Machine Hub Table
    total_cycles = Column(Integer, default=0)
    avg_detergent = Column(Float, default=0.0)
    avg_electricity = Column(Float, default=0.0)
    avg_water = Column(Float, default=0.0)
    
    # Real-time Monitoring Countdown (value in minutes)
    remaining_time = Column(Integer, default=0) 
    
    shop_id = Column(Integer, ForeignKey("shops.id"))

    # Relationships
    shop = relationship("Shop", back_populates="machines")
    
    # Link to bookings: Essential for identifying which machines are tied to active orders.
    # Note: Using string-based foreign keys in relationship for stability.
    washer_bookings = relationship(
        "Booking", 
        foreign_keys="Booking.washer_id", 
        back_populates="washer"
    )
    dryer_bookings = relationship(
        "Booking", 
        foreign_keys="Booking.dryer_id", 
        back_populates="dryer"
    )

class Booking(Base):
    """
    Stores all laundry transactions and customer service details.
    Directly references Machine IDs to automate status triggers (Busy/Available).
    """
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, nullable=False)
    
    # Service Configuration
    service_type = Column(String, nullable=False) # e.g., 'Full Service', 'Self-Service'
    category = Column(String, nullable=False)     # e.g., 'Clothes', 'Linens'
    weight = Column(Float, nullable=False)
    loads = Column(Integer, default=1)
    
    # Pricing & Operational Mode
    total_price = Column(Float, nullable=False)
    booking_mode = Column(String, nullable=False) # 'smart' or 'manual'
    
    # Operational Flags
    add_detergent = Column(Boolean, default=False)
    add_delivery = Column(Boolean, default=False)
    is_rush = Column(Boolean, default=False)

    # Workflow Status: 'Pending', 'In Progress', 'Ready', 'Claimed'
    status = Column(String, default="Pending")
    
    # Hardware Assignment Links
    # References the primary key 'id' in 'machines' table
    washer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    dryer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    
    shop_id = Column(Integer, ForeignKey("shops.id"))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    shop = relationship("Shop", back_populates="bookings")
    
    # Hardware assignments
    # 'lazy="joined"' sinisiguro nito na kapag kinuha ang Booking, kasama na agad ang Machine data.
    # Ito ang solusyon para makita ng frontend ang machine_number (W1, D3).
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