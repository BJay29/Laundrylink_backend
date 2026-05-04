from app.database import Base
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

class Shop(Base):
    """
    Represents a laundry business entity. 
    Stores business-wide data like the shop name and its physical location.
    """
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True, index=True)
    shop_name = Column(String, unique=True, nullable=False)
    address = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    users = relationship("User", back_populates="shop")
    machines = relationship("Machine", back_populates="shop", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="shop")

class User(Base):
    """
    Central Authentication table for the Laundry System. 
    Stores login credentials for Owners and Staff.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False) 
    role = Column(String, nullable=False) # 'owner' or 'staff'
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    shop = relationship("Shop", back_populates="users")

class Machine(Base):
    """
    Represents hardware units (Washers/Dryers).
    Updated to support the Machine Hub table view (image_b6637f.png).
    """
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)
    machine_type = Column(String, nullable=False) # 'Washer' or 'Dryer'
    machine_number = Column(Integer, nullable=False) # e.g., 1, 2, 3
    
    # Status levels: 'Available', 'Busy', 'Maintenance'
    status = Column(String, default="Available")
    
    # Performance Metrics for Machine Hub Table
    total_cycles = Column(Integer, default=0)
    avg_detergent = Column(Float, default=0.0)  # Calculated as: total_detergent_cost / total_cycles
    avg_electricity = Column(Float, default=0.0) # Calculated as: total_elec_cost / total_cycles
    avg_water = Column(Float, default=0.0)       # Calculated as: total_water_cost / total_cycles
    
    # Real-time Monitoring
    remaining_time = Column(Integer, default=0) # Countdown in minutes
    
    shop_id = Column(Integer, ForeignKey("shops.id"))

    # Relationships
    shop = relationship("Shop", back_populates="machines")
    
    # Linked to bookings (Multiple bookings can be associated with a machine over time)
    washer_bookings = relationship("Booking", foreign_keys="[Booking.washer_id]", back_populates="washer")
    dryer_bookings = relationship("Booking", foreign_keys="[Booking.dryer_id]", back_populates="dryer")

class Booking(Base):
    """
    Stores all laundry transactions.
    Updated to link to specific Washer and Dryer units to automate status updates.
    """
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, nullable=False)
    
    # Service Details
    service_type = Column(String, nullable=False) # e.g., 'Full Service'
    category = Column(String, nullable=False)      # e.g., 'Clothes', 'Linens'
    weight = Column(Float, nullable=False)
    loads = Column(Integer, default=1)
    
    # Pricing & Mode
    total_price = Column(Float, nullable=False)
    booking_mode = Column(String, nullable=False) # 'smart' or 'manual'
    
    # Add-ons
    add_detergent = Column(Boolean, default=False)
    add_delivery = Column(Boolean, default=False)
    is_rush = Column(Boolean, default=False)

    # Status: 'Pending', 'In Progress', 'Ready', 'Claimed'
    status = Column(String, default="Pending")
    
    # Hardware Assignment
    # Linking to both allows the controller to set both machines to 'Busy' simultaneously
    washer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    dryer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    
    shop_id = Column(Integer, ForeignKey("shops.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    shop = relationship("Shop", back_populates="bookings")
    washer = relationship("Machine", foreign_keys=[washer_id], back_populates="washer_bookings")
    dryer = relationship("Machine", foreign_keys=[dryer_id], back_populates="dryer_bookings")