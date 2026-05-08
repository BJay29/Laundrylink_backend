from sqlalchemy.orm import Session
from .. import models, schemas

# Define "Factory Defaults" as a constant to ensure they are always recoverable.
# These values match the updated specific service types for the laundry system.
SYSTEM_DEFAULTS = {
    "full_service_price": 210.0,
    "regular_wash_price": 65.0,
    "titan_wash_price": 100.0,
    "comforter_price": 150.0,
    "electricity_rate": 12.0,
    "water_rate": 50.0,
    "detergent_cost_per_load": 10.0,
    "off_peak_hours": "8:00 AM - 11:00 AM"
}

def get_settings(db: Session, shop_id: int):
    """
    Retrieves the optimization settings for a specific shop.
    If no settings exist yet, it creates an entry using SYSTEM_DEFAULTS.
    """
    settings = db.query(models.Setting).filter(models.Setting.shop_id == shop_id).first()
    
    if not settings:
        # Create default settings using the SYSTEM_DEFAULTS constant if row is missing
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
    Returns the hardcoded system default values.
    Used by the frontend to show the 'original' prices before the user saves changes.
    """
    return SYSTEM_DEFAULTS

def update_settings(db: Session, shop_id: int, settings_data: schemas.SettingUpdate):
    """
    Updates the business parameters and operational costs in the database.
    These changes will immediately reflect in the Booking Modal and Profit Forecasts.
    """
    db_settings = db.query(models.Setting).filter(models.Setting.shop_id == shop_id).first()
    
    # Extract only the data that was sent in the request (partial updates)
    update_data = settings_data.model_dump(exclude_unset=True)

    if not db_settings:
        # Fallback: If settings row doesn't exist, create it with provided data
        db_settings = models.Setting(shop_id=shop_id, **update_data)
        db.add(db_settings)
    else:
        # Update existing record fields dynamically using setattr
        for key, value in update_data.items():
            setattr(db_settings, key, value)
    
    db.commit()
    db.refresh(db_settings)
    return db_settings

def reset_to_system_defaults(db: Session, shop_id: int):
    """
    Reverts the shop's database record back to the original SYSTEM_DEFAULTS.
    This effectively clears any custom pricing set by the owner.
    """
    db_settings = db.query(models.Setting).filter(models.Setting.shop_id == shop_id).first()
    
    if db_settings:
        # Overwrite all custom values with system-wide defaults
        for key, value in SYSTEM_DEFAULTS.items():
            setattr(db_settings, key, value)
        db.commit()
        db.refresh(db_settings)
        return db_settings
    
    # If no settings existed at all, just initialize them
    return get_settings(db, shop_id)

def get_pricing_for_booking(db: Session, shop_id: int):
    """
    Helper function specifically for the Booking Modal.
    Returns a mapped dictionary where keys match the specific 'service_type' 
    labels used in the frontend booking logic.
    """
    settings = get_settings(db, shop_id)
    return {
        "Full Service": settings.full_service_price,
        "Regular Wash": settings.regular_wash_price,
        "Titan Wash": settings.titan_wash_price,
        "Comforter": settings.comforter_price,
        "detergent_fee": settings.detergent_cost_per_load
    }