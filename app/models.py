from app.database import Base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
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
    # One shop can have multiple users (e.g., one Owner and several Staff)
    users = relationship("User", back_populates="shop")

class User(Base):
    """
    Central Authentication table for the Laundry System. 
    Stores login credentials for Owners and Staff to manage income optimization.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    
    # Auth & Identity
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False) 
    role = Column(String, nullable=False) # Roles: 'owner' or 'staff'
    
    # Organizational Link
    # Since we are focusing on shop management, shop_id is essential
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True)
    
    # Account Status
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    # Link back to the Shop table to retrieve shop_name and address during login
    shop = relationship("Shop", back_populates="users")