from sqlalchemy.orm import Session
from .. import models, schemas
import logging

# Set up logging to track if the system is falling back to defaults
logger = logging.getLogger(__name__)

# --- SYSTEM CONSTANTS ---
# These are strictly "Factory Defaults" used ONLY for new shop initialization 
# or manual resets. They should NOT be used for active calculations.
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
    Returns the hardcoded system default values.
    Provides the frontend with the 'Standard' reference prices.
    """
    return SYSTEM_DEFAULTS

def update_settings(db: Session, shop_id: int, settings_data: schemas.SettingUpdate):
    """
    Updates the business parameters and pricing in the database.
    This change triggers an immediate update for the Booking Modal and Analytics.
    """
    db_settings = db.query(models.Setting).filter(models.Setting.shop_id == shop_id).first()
    
    # Exclude unset values to allow partial updates (e.g., only updating one price)
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
    Wipes custom pricing and reverts the shop's DB record to SYSTEM_DEFAULTS.
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
    Maps database column values to the specific 'service_type' keys 
    expected by the React frontend logic.
    """
    # Fetch the LATEST settings directly from the DB
    settings = get_settings(db, shop_id)
    
    # Verification log to ensure the values fetched are correct
    logger.info(f"Fetching Live Pricing for Shop {shop_id}: Full Service = {settings.full_service_price}")

    # The keys here must match the 'service_type' selection in the Frontend
    return {
        "Full Service": float(settings.full_service_price),
        "Regular Wash": float(settings.regular_wash_price),
        "Titan Wash": float(settings.titan_wash_price),
        "Comforter": float(settings.comforter_price),
        "detergent_fee": float(settings.detergent_cost_per_load)
    }