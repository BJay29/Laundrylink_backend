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
    Hardware units tracking state and performance.
    """
    __tablename__ = "machines"

    id = Column(Integer, primary_key=True, index=True)
    machine_type = Column(String, nullable=False) # 'Washer' or 'Dryer'
    machine_number = Column(Integer, nullable=False)
    
    status = Column(String, default="Available") 
    current_service_type = Column(String, default="None")
    current_price = Column(Float, default=0.0)
    remaining_time = Column(Integer, default=0) 
    
    total_cycles = Column(Integer, default=0)
    net_profit_accumulated = Column(Float, default=0.0)
    
    avg_electricity = Column(Float, default=1.2)
    avg_water = Column(Float, default=60.0)
    avg_detergent = Column(Float, default=45.0)
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False) # Ginawa nating False para iwas sync error
    shop = relationship("Shop", back_populates="machines")

    # Relationship names simplified for clarity
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
            "current_service_type": self.current_service_type,
            "current_price": self.current_price,
            "total_cycles": self.total_cycles,
            "net_profit_accumulated": self.net_profit_accumulated,
            "avg_detergent": self.avg_detergent,
            "avg_electricity": self.avg_electricity,
            "avg_water": self.avg_water,
            "remaining_time": self.remaining_time,
            "shop_id": self.shop_id
        }

class Booking(Base):
    """
    Connects customers to specific hardware units via ID.
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

    status = Column(String, default="Pending")
    
    # Siguraduhin na ang input dito ay MACHINE ID, hindi machine number.
    washer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    dryer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    shop = relationship("Shop", back_populates="bookings")
    
    # Joined loading para mabilis makuha ang machine_number sa frontend
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
        # Dagdag machine_number sa dictionary para hindi malito ang UI
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
            "washer_number": self.washer.machine_number if self.washer else None,
            "dryer_number": self.dryer.machine_number if self.dryer else None,
            "shop_id": self.shop_id,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }