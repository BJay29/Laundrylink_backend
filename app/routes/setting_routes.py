from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..database import get_db
from .. import schemas
from ..controller import settings_controller

# Define the router with a prefix for clean API organization
router = APIRouter(
    prefix="/settings",
    tags=["Settings"]
)

@router.get("/defaults", response_model=dict)
def get_system_defaults():
    """
    Fetch the hardcoded factory default pricing and configuration.
    Used by the frontend to preview default values when the user clicks 'Reset to Defaults'.
    """
    try:
        # Fetches the SYSTEM_DEFAULTS constant from the controller
        return settings_controller.get_factory_defaults()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch default settings: {str(e)}")

@router.get("/{shop_id}", response_model=schemas.SettingResponse)
def get_shop_settings(shop_id: int, db: Session = Depends(get_db)):
    """
    Fetch the current pricing and operational configurations for the dashboard.
    This ensures the UI reflects the most recent saved data from the database.
    """
    settings = settings_controller.get_settings(db, shop_id)
    if not settings:
        raise HTTPException(status_code=404, detail="Settings not found for this shop")
    return settings

@router.put("/{shop_id}", response_model=schemas.SettingResponse)
def update_shop_settings(
    shop_id: int, 
    settings_update: schemas.SettingUpdate, 
    db: Session = Depends(get_db)
):
    """
    Update business parameters such as service prices and utility rates.
    Propagates changes to the Booking Modal and Financial Forecasts.
    """
    try:
        updated_settings = settings_controller.update_settings(db, shop_id, settings_update)
        return updated_settings
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")

@router.post("/{shop_id}/reset", response_model=schemas.SettingResponse)
def reset_shop_settings(shop_id: int, db: Session = Depends(get_db)):
    """
    Hard reset endpoint to revert database entries back to factory defaults.
    Triggered when the user confirms a 'Reset and Save' action in the UI.
    """
    try:
        return settings_controller.reset_to_system_defaults(db, shop_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset settings to default: {str(e)}")

@router.get("/{shop_id}/pricing", response_model=dict)
def get_booking_pricing(shop_id: int, db: Session = Depends(get_db)):
    """
    Lightweight endpoint specifically for the Booking Modal.
    Returns only essential pricing fields to minimize payload size and speed up modal loading.
    """
    pricing = settings_controller.get_pricing_for_booking(db, shop_id)
    if not pricing:
        raise HTTPException(status_code=404, detail="Pricing data unavailable")
    return pricing