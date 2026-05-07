from app.database import Base
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey
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
    
    # Primary Financial Source for Dashboard/Terminal logic
    net_profit_accumulated = Column(Float, default=0.0)
    profitability_rate = Column(Float, default=0.0) 
    
    # Accumulated Utility Costs for Telemetry tracking
    accumulated_electricity = Column(Float, default=0.0) 
    accumulated_water = Column(Float, default=0.0)       
    accumulated_detergent = Column(Float, default=0.0)   
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    shop = relationship("Shop", back_populates="machines")

    # Transaction history mapping using explicit foreign keys
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
        # Calculate total overhead for the metrics object
        overhead = (self.accumulated_electricity or 0.0) + \
                   (self.accumulated_water or 0.0) + \
                   (self.accumulated_detergent or 0.0)
        
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
    Laundry transactions linking customers to hardware units.
    Updated with booking_timestamp to facilitate AI Peak-Hour Forecasting.
    """
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, nullable=False)
    
    # Service Configuration
    service_type = Column(String, nullable=False) 
    category = Column(String, nullable=False)
    weight = Column(Float, nullable=False)
    loads = Column(Integer, default=1)
    
    total_price = Column(Float, nullable=False)
    booking_mode = Column(String, nullable=False) # e.g., 'smart' or 'manual'
    
    # Estimated duration in minutes
    service_duration = Column(Integer, default=45) 
    
    # Optional modifiers
    add_detergent = Column(Boolean, default=False)
    add_delivery = Column(Boolean, default=False)
    is_rush = Column(Boolean, default=False)

    status = Column(String, default="Pending") 
    
    # Foreign Key Assignments for Washers and Dryers
    washer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    dryer_id = Column(Integer, ForeignKey("machines.id"), nullable=True)
    
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    
    # AI Prediction Metrics: Captures exact time for forecasting models
    booking_timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships with joined loading for frontend terminal performance
    shop = relationship("Shop", back_populates="bookings")
    
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
        """
        Custom serialization to return readable machine labels (W1/D1) 
        and ISO formatted timestamps to the React Service Terminal.
        """
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
            # Provides labels for the UI Table (e.g., "Washer #1")
            "washer_number": self.washer.machine_number if self.washer else None,
            "dryer_number": self.dryer.machine_number if self.dryer else None,
            "shop_id": self.shop_id,
            # Ensure timestamps are ISO strings for JavaScript Date parsing
            "booking_timestamp": self.booking_timestamp.isoformat() if self.booking_timestamp else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }