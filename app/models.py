from app.database import Base
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

class Shop(Base):
    """
    Represents a laundry business entity. 
    Stores business-wide data like name and location.
    """
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True, index=True)
    shop_name = Column(String, unique=True, nullable=False)
    address = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    # Link back to users (Owners/Staff) associated with this shop
    users = relationship("User", back_populates="shop")

class User(Base):
    """
    Central Authentication table. 
    Stores login credentials and handles role-based access.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    
    # Auth & Identity
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False) 
    role = Column(String, nullable=False) # 'owner' or 'customer'
    
    # Organizational Link
    # Nullable because customers are not tied to a specific shop row
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True)
    
    # SSO / Federated Identity
    google_id = Column(String, unique=True, nullable=True)
    auth_provider = Column(String, default="manual") 
    
    # Account Status
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    shop = relationship("Shop", back_populates="users")
    
    # One-to-One relationship with the Customer Profilea
    customer_profile = relationship("CustomerProfile", back_populates="user", uselist=False)

class CustomerProfile(Base):
    """
    Stores profile data exclusive to Mobile App Users (Customers).
    Separated to keep the main User table clean.
    """
    __tablename__ = "customer_profiles"

    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign Key linking to the base User
    # ondelete="CASCADE" ensures profile is deleted if user is deleted
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    
    # Personal Details
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    phone_number = Column(String, unique=True, nullable=False)
    address = Column(String, nullable=True)

    # Relationships
    user = relationship("User", back_populates="customer_profile")