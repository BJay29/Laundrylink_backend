from sqlalchemy.orm import Session
from .. import models, schemas

# Define "Factory Defaults" as a constant to ensure they are always recoverable
SYSTEM_DEFAULTS = {
    "wash_only_price": 40.0,
    "dry_only_price": 30.0,
    "full_service_price": 60.0,
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
        # Create default settings using the SYSTEM_DEFAULTS constant
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
    Used by the frontend when the user clicks 'Reset to Defaults'.
    """
    return SYSTEM_DEFAULTS

def update_settings(db: Session, shop_id: int, settings_data: schemas.SettingUpdate):
    """
    Updates the business parameters and operational costs in the database.
    These changes will immediately reflect in the Booking Modal and Profit Forecasts.
    """
    db_settings = db.query(models.Setting).filter(models.Setting.shop_id == shop_id).first()
    
    # Extract only the data that was sent in the request
    update_data = settings_data.model_dump(exclude_unset=True)

    if not db_settings:
        # Fallback: If settings don't exist, create them with the provided data
        db_settings = models.Setting(shop_id=shop_id, **update_data)
        db.add(db_settings)
    else:
        # Update existing record fields dynamically
        for key, value in update_data.items():
            setattr(db_settings, key, value)
    
    db.commit()
    db.refresh(db_settings)
    return db_settings

def reset_to_system_defaults(db: Session, shop_id: int):
    """
    Reverts the shop's database entry back to the original SYSTEM_DEFAULTS.
    """
    db_settings = db.query(models.Setting).filter(models.Setting.shop_id == shop_id).first()
    
    if db_settings:
        for key, value in SYSTEM_DEFAULTS.items():
            setattr(db_settings, key, value)
        db.commit()
        db.refresh(db_settings)
        return db_settings
    
    return get_settings(db, shop_id)

def get_pricing_for_booking(db: Session, shop_id: int):
    """
    Helper function specifically for the Booking Modal to fetch current rates.
    """
    settings = get_settings(db, shop_id)
    return {
        "wash_only": settings.wash_only_price,
        "dry_only": settings.dry_only_price,
        "full_service": settings.full_service_price,
        "detergent": settings.detergent_cost_per_load
    }