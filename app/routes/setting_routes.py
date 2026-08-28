from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from .. import schemas
from ..controller import settings_controller, auth_controller # Assuming auth_controller handles user session

# Define the router with a prefix for clean API organization
router = APIRouter(
    prefix="/settings",
    tags=["Settings"]
)

@router.get("/defaults", response_model=dict)
def get_system_defaults():
    """
    Fetch the hardcoded factory default operational rates (electricity,
    water, detergent cost, minimum weight, off-peak hours). Service pricing
    is NOT included here anymore — that's fully owner-defined via the
    /settings/{shop_id}/services endpoints below.
    """
    try:
        return settings_controller.get_factory_defaults()
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to fetch system default settings: {str(e)}"
        )

@router.get("/{shop_id}", response_model=schemas.SettingResponse)
def get_shop_settings(shop_id: int, db: Session = Depends(get_db)):
    """
    Fetch the current operational configuration for a specific shop
    (utility rates, minimum weight, off-peak hours). Service pricing lives
    separately under /settings/{shop_id}/services.
    """
    settings = settings_controller.get_settings(db, shop_id)
    if not settings:
        raise HTTPException(
            status_code=404, 
            detail=f"Settings for Shop ID {shop_id} not found"
        )
    return settings

@router.put("/{shop_id}", response_model=schemas.SettingResponse)
def update_shop_settings(
    shop_id: int, 
    settings_update: schemas.SettingUpdate, 
    db: Session = Depends(get_db)
):
    """
    Update business parameters such as utility rates and minimum weight.
    Propagates changes immediately to the Booking Modal.
    """
    try:
        updated_settings = settings_controller.update_settings(db, shop_id, settings_update)
        return updated_settings
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error updating settings for Shop {shop_id}: {str(e)}"
        )

@router.post("/{shop_id}/reset", response_model=schemas.SettingResponse)
def reset_shop_settings(shop_id: int, db: Session = Depends(get_db)):
    """
    Hard reset endpoint to revert operational rates back to factory defaults.
    Does NOT delete or modify the shop's configured service types/prices —
    those are owner-defined and are left untouched by this reset.
    """
    try:
        return settings_controller.reset_to_system_defaults(db, shop_id)
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to revert settings to defaults for Shop {shop_id}: {str(e)}"
        )

@router.get("/{shop_id}/pricing", response_model=dict)
def get_booking_pricing(shop_id: int, db: Session = Depends(get_db)):
    """
    Lightweight endpoint specifically for the Booking Modal.
    Returns a dynamic pricing map built from the shop's active ServiceType
    records (keys are whatever service names the owner configured), plus
    'detergent_fee' and 'minimum_weight_kg'. Returns an empty map (aside
    from those two keys) if the shop hasn't configured any services yet —
    the frontend should show a "configure your services" state in that case.
    """
    pricing = settings_controller.get_pricing_for_booking(db, shop_id)
    if pricing is None:
        raise HTTPException(
            status_code=404, 
            detail="Pricing data unavailable for the booking transaction"
        )
    return pricing

# --- SERVICE TYPE ROUTES (NEW) ---

@router.get("/{shop_id}/services", response_model=List[schemas.ServiceTypeResponse])
def list_service_types(shop_id: int, db: Session = Depends(get_db)):
    """
    Lists all services (active and inactive) configured for the shop.
    Used by the Optimization Settings page to manage the service catalog.
    A brand-new shop will return an empty list until the owner adds one.
    """
    return settings_controller.get_service_types(db, shop_id)

@router.post("/{shop_id}/services", response_model=schemas.ServiceTypeResponse, status_code=status.HTTP_201_CREATED)
def add_service_type(shop_id: int, service_data: schemas.ServiceTypeCreate, db: Session = Depends(get_db)):
    """
    Adds a new service (name + price) to the shop's catalog.
    This is how a shop owner populates the Service Type dropdown that
    appears in the Create Booking modal.
    """
    return settings_controller.create_service_type(db, shop_id, service_data)

@router.put("/{shop_id}/services/{service_id}", response_model=schemas.ServiceTypeResponse)
def edit_service_type(
    shop_id: int,
    service_id: int,
    service_data: schemas.ServiceTypeUpdate,
    db: Session = Depends(get_db)
):
    """
    Updates an existing service's name, price, or active status.
    Setting is_active=false hides it from new bookings without deleting
    its historical record.
    """
    return settings_controller.update_service_type(db, shop_id, service_id, service_data)

@router.delete("/{shop_id}/services/{service_id}", status_code=status.HTTP_200_OK)
def remove_service_type(shop_id: int, service_id: int, db: Session = Depends(get_db)):
    """
    Permanently removes a service from the shop's catalog.
    Past bookings that used this service keep their stored service_type
    string and are unaffected.
    """
    return settings_controller.delete_service_type(db, shop_id, service_id)

# --- PROFILE & PASSWORD ROUTES ---

@router.put("/{shop_id}/profile", response_model=schemas.ShopProfileResponse)
def update_shop_profile(shop_id: int, profile_update: schemas.ShopProfileUpdate, db: Session = Depends(get_db)):
    """
    Update shop name, address, and contact email.
    """
    updated_shop = settings_controller.update_shop_profile(db, shop_id, profile_update)
    if not updated_shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return updated_shop

@router.put("/user/{user_id}/password")
def update_password(user_id: int, password_update: schemas.PasswordUpdate, db: Session = Depends(get_db)):
    """
    Update user password after verifying current credentials.
    """
    result = settings_controller.update_user_password(db, user_id, password_update)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result