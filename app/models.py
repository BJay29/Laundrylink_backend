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
    machines = relationship("Machine", back_populates="shop")
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
    Updated to support the Machine Hub monitoring, profitability tracking, 
    and maintenance status logic.
    """
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)
    machine_type = Column(String, nullable=False) # 'Washer' or 'Dryer'
    machine_number = Column(Integer, nullable=False) # Fixed units: 1, 2, 3, 4, 5, 6
    
    # Status levels: 'Available', 'Active', 'Maintenance'
    # 'Maintenance' blocks the machine from being selected in the Booking Modal
    status = Column(String, default="Available") 
    
    # Availability flag for frontend filtering
    is_available = Column(Boolean, default=True) 
    
    # Usage and Profitability Metrics
    total_cycles = Column(Integer, default=0) # Increments every time a booking is completed
    profitability_score = Column(Float, default=0.0) # Percentage based on usage vs overhead
    estimated_cost_per_cycle = Column(Float, default=0.0) # Utility overhead (electricity/water)
    
    shop_id = Column(Integer, ForeignKey("shops.id"))

    # Relationships
    shop = relationship("Shop", back_populates="machines")
    # Link to bookings to track real-time machine assignment
    active_bookings = relationship("Booking", back_populates="assigned_machine")

class Booking(Base):
    """
    Stores all laundry transactions.
    Updated to link directly with Machine IDs to trigger 'Active' status.
    """
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, nullable=False)
    
    # Service Details
    service_type = Column(String, nullable=False) # E.g., 'Full Service'
    category = Column(String, nullable=False) # E.g., 'Clothes', 'Linens'
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
    # Selecting this ID in the modal should update the Machine status to 'Active'
    machine_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    shop_id = Column(Integer, ForeignKey("shops.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    shop = relationship("Shop", back_populates="bookings")
    assigned_machine = relationship("Machine", back_populates="active_bookings")