from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from .. import models, schemas
import logging
from passlib.context import CryptContext # Added for password hashing

# Set up password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Set up logging to track if the system is falling back to defaults
logger = logging.getLogger(__name__)

# --- SYSTEM CONSTANTS ---
# These are strictly "Factory Defaults" used ONLY for new shop initialization
# or manual resets of OPERATIONAL RATES. They should NOT be used for active
# calculations. Service pricing (Full Service, Regular Wash, etc.) is no
# longer part of these defaults — shop owners define their own services
# via the ServiceType table, starting from an empty catalog.
SYSTEM_DEFAULTS = {
    "electricity_rate": 12.0,
    "water_rate": 50.0,
    "detergent_cost_per_load": 10.0,
    "minimum_weight_kg": 6.0,
    "off_peak_hours": "8:00 AM - 11:00 AM"
}

# --- SETTINGS FUNCTIONS ---

def get_settings(db: Session, shop_id: int):
    """
    Retrieves the optimization settings for a specific shop.
    If no settings exist in the database, it initializes them using SYSTEM_DEFAULTS.
    """
    settings = db.query(models.Setting).filter(models.Setting.shop_id == shop_id).first()
    
    if not settings:
        logger.info(f"No settings found for shop_id {shop_id}. Initializing with defaults.")
        # Create a new record in the database so the user can modify it later.
        settings = models.Setting(
            shop_id=shop_id,
            **SYSTEM_DEFAULTS
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    
    return settings

def get_factory_defaults():
    """
    Returns the hardcoded system default values for operational rates.
    Provides the frontend with the 'Standard' reference values. Service
    pricing is not included here since it is fully owner-defined.
    """
    return SYSTEM_DEFAULTS

def update_settings(db: Session, shop_id: int, settings_data: schemas.SettingUpdate):
    """
    Updates the business parameters and operational rates in the database.
    This change triggers an immediate update for the Booking Modal and Analytics.
    """
    db_settings = db.query(models.Setting).filter(models.Setting.shop_id == shop_id).first()
    
    # Exclude unset values to allow partial updates (e.g., only updating one rate)
    update_data = settings_data.model_dump(exclude_unset=True)

    if not db_settings:
        # Create new record if it doesn't exist
        db_settings = models.Setting(shop_id=shop_id, **update_data)
        db.add(db_settings)
    else:
        # Dynamically update existing fields
        for key, value in update_data.items():
            if hasattr(db_settings, key):
                setattr(db_settings, key, value)
    
    db.commit()
    db.refresh(db_settings)
    logger.info(f"Settings successfully updated for shop_id {shop_id}.")
    return db_settings

def reset_to_system_defaults(db: Session, shop_id: int):
    """
    Wipes custom operational rates and reverts the shop's DB record to
    SYSTEM_DEFAULTS. Does NOT touch ServiceType records — service pricing
    is reset separately (or not at all) since it's fully owner-defined.
    """
    db_settings = db.query(models.Setting).filter(models.Setting.shop_id == shop_id).first()
    
    if db_settings:
        for key, value in SYSTEM_DEFAULTS.items():
            if hasattr(db_settings, key):
                setattr(db_settings, key, value)
        db.commit()
        db.refresh(db_settings)
        return db_settings
    
    return get_settings(db, shop_id)

def get_pricing_for_booking(db: Session, shop_id: int):
    """
    Crucial helper for the Booking Modal.
    UPDATED: Instead of returning 4 hardcoded service keys, this now builds
    the pricing map dynamically from whatever ServiceType records the shop
    owner has configured. If the shop hasn't added any services yet, this
    returns an empty pricing map (frontend should show an empty/"configure
    your services" state rather than a fixed dropdown).
    """
    settings = get_settings(db, shop_id)

    active_services = (
        db.query(models.ServiceType)
        .filter(models.ServiceType.shop_id == shop_id, models.ServiceType.is_active == True)
        .order_by(models.ServiceType.id.asc())
        .all()
    )

    pricing = {service.name: float(service.price) for service in active_services}

    logger.info(f"Fetching Live Pricing for Shop {shop_id}: {len(pricing)} active service(s) found.")

    pricing["detergent_fee"] = float(settings.detergent_cost_per_load)
    pricing["minimum_weight_kg"] = float(settings.minimum_weight_kg or 6.0)

    return pricing

# --- SERVICE TYPE FUNCTIONS (NEW) ---

def get_service_types(db: Session, shop_id: int):
    """
    Returns all services (active and inactive) configured for a shop,
    for display and management on the Optimization Settings page.
    """
    return (
        db.query(models.ServiceType)
        .filter(models.ServiceType.shop_id == shop_id)
        .order_by(models.ServiceType.id.asc())
        .all()
    )

def create_service_type(db: Session, shop_id: int, service_data: schemas.ServiceTypeCreate):
    """
    Registers a new service (name + price) for the shop.
    Prevents exact duplicate names (case-insensitive) for the same shop.
    """
    existing = (
        db.query(models.ServiceType)
        .filter(
            models.ServiceType.shop_id == shop_id,
            models.ServiceType.name.ilike(service_data.name)
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A service named '{service_data.name}' already exists for this shop."
        )

    new_service = models.ServiceType(
        name=service_data.name,
        price=service_data.price,
        is_active=service_data.is_active,
        shop_id=shop_id
    )
    db.add(new_service)
    db.commit()
    db.refresh(new_service)
    return new_service

def update_service_type(db: Session, shop_id: int, service_id: int, service_data: schemas.ServiceTypeUpdate):
    """
    Edits an existing service's name, price, or active status.
    """
    service = (
        db.query(models.ServiceType)
        .filter(models.ServiceType.id == service_id, models.ServiceType.shop_id == shop_id)
        .first()
    )
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service type not found.")

    update_data = service_data.model_dump(exclude_unset=True)

    if "name" in update_data:
        duplicate = (
            db.query(models.ServiceType)
            .filter(
                models.ServiceType.shop_id == shop_id,
                models.ServiceType.name.ilike(update_data["name"]),
                models.ServiceType.id != service_id
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A service named '{update_data['name']}' already exists for this shop."
            )

    for key, value in update_data.items():
        setattr(service, key, value)

    db.commit()
    db.refresh(service)
    return service

def delete_service_type(db: Session, shop_id: int, service_id: int):
    """
    Removes a service from the shop's catalog.
    Existing bookings keep their historical service_type string, so past
    records are unaffected — only future bookings lose this as an option.
    """
    service = (
        db.query(models.ServiceType)
        .filter(models.ServiceType.id == service_id, models.ServiceType.shop_id == shop_id)
        .first()
    )
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service type not found.")

    db.delete(service)
    db.commit()
    return {"message": f"Service '{service.name}' removed successfully."}

# --- PROFILE & SECURITY FUNCTIONS (NEW) ---

def update_shop_profile(db: Session, shop_id: int, profile_data: schemas.ShopProfileUpdate):
    """
    Updates the shop's contact information and business profile.
    """
    db_shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not db_shop:
        return None
    
    update_data = profile_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(db_shop, key):
            setattr(db_shop, key, value)
            
    db.commit()
    db.refresh(db_shop)
    return db_shop

def update_user_password(db: Session, user_id: int, password_data: schemas.PasswordUpdate):
    """
    Validates the old password and updates to a new hashed password.
    """
    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        return {"error": "User not found"}
    
    # Verify old password
    if not pwd_context.verify(password_data.old_password, db_user.hashed_password):
        return {"error": "Incorrect old password"}
    
    # Update to new hashed password
    db_user.hashed_password = pwd_context.hash(password_data.new_password)
    db.commit()
    return {"message": "Password updated successfully"}