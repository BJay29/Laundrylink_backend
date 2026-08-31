from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from .. import schemas, models
from ..controller import settings_controller
from ..security import get_current_user

# Define the router with a prefix for clean API organization
router = APIRouter(
    prefix="/settings",
    tags=["Settings"]
)


@router.get("/defaults", response_model=dict)
def get_system_defaults():
    """
    Fetch the hardcoded factory default operational rates (electricity,
    water, detergent cost, minimum weight, off-peak hours). Not shop-specific,
    so no auth needed here — these are just static reference values.
    """
    try:
        return settings_controller.get_factory_defaults()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch system default settings: {str(e)}"
        )


@router.get("/", response_model=schemas.SettingResponse)
def get_shop_settings(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Fetch the current operational configuration for the logged-in user's
    own shop (utility rates, minimum weight, off-peak hours).
    shop_id is derived from the JWT, not the URL — a user can never
    view another shop's settings by editing the path.
    Read-only — no controller signature change needed here.
    """
    settings = settings_controller.get_settings(db, current_user.shop_id)
    if not settings:
        raise HTTPException(
            status_code=404,
            detail="Settings for your shop were not found"
        )
    return settings


@router.put("/", response_model=schemas.SettingResponse)
def update_shop_settings(
    settings_update: schemas.SettingUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update business parameters such as utility rates and minimum weight
    for the logged-in user's own shop. Propagates changes immediately
    to the Booking Modal.

    UPDATED: settings_controller.update_settings() now takes current_user
    (not shop_id) so the resulting Activity Log entry can attribute this
    action to whoever performed it.
    """
    try:
        return settings_controller.update_settings(db, current_user, settings_update)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error updating settings: {str(e)}"
        )


@router.post("/reset", response_model=schemas.SettingResponse)
def reset_shop_settings(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Hard reset endpoint to revert the logged-in user's shop operational
    rates back to factory defaults. Does NOT touch configured service
    types/prices — those are owner-defined and left untouched.

    UPDATED: settings_controller.reset_to_system_defaults() now takes
    current_user (not shop_id) for Activity Log attribution.
    """
    try:
        return settings_controller.reset_to_system_defaults(db, current_user)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to revert settings to defaults: {str(e)}"
        )


@router.get("/pricing", response_model=dict)
def get_booking_pricing(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lightweight endpoint specifically for the Booking Modal.
    Returns a dynamic pricing map built from the logged-in user's shop's
    active ServiceType records, plus 'detergent_fee' and 'minimum_weight_kg'.
    Read-only — no controller signature change needed here.
    """
    pricing = settings_controller.get_pricing_for_booking(db, current_user.shop_id)
    if pricing is None:
        raise HTTPException(
            status_code=404,
            detail="Pricing data unavailable for the booking transaction"
        )
    return pricing


# --- SERVICE TYPE ROUTES ---

@router.get("/services", response_model=List[schemas.ServiceTypeResponse])
def list_service_types(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lists all services (active and inactive) configured for the logged-in
    user's shop. A brand-new shop will return an empty list until the
    owner adds one.
    Read-only — no controller signature change needed here.
    """
    return settings_controller.get_service_types(db, current_user.shop_id)


@router.post("/services", response_model=schemas.ServiceTypeResponse, status_code=status.HTTP_201_CREATED)
def add_service_type(
    service_data: schemas.ServiceTypeBase,  # dating ServiceTypeCreate, na may
    # REQUIRED shop_id field. Dahil hindi na nagpapadala ang frontend ng
    # shop_id sa body (JWT na ang pinagmumulan nito), ServiceTypeBase
    # (walang shop_id) ang tamang schema dito.
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Adds a new service (name + price + duration_minutes) to the logged-in
    user's shop catalog. This is how a shop owner populates the Service
    Type dropdown that appears in the Create Booking modal.

    UPDATED: settings_controller.create_service_type() now takes
    current_user (not shop_id) for Activity Log attribution.
    """
    return settings_controller.create_service_type(db, current_user, service_data)


@router.put("/services/{service_id}", response_model=schemas.ServiceTypeResponse)
def edit_service_type(
    service_id: int,
    service_data: schemas.ServiceTypeUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Updates an existing service's name, price, active status, or duration.
    Setting is_active=false hides it from new bookings without deleting
    its historical record. Scoped to the logged-in user's own shop.

    UPDATED: settings_controller.update_service_type() now takes
    current_user (not shop_id) for Activity Log attribution.
    """
    return settings_controller.update_service_type(db, current_user, service_id, service_data)


@router.delete("/services/{service_id}", status_code=status.HTTP_200_OK)
def remove_service_type(
    service_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Permanently removes a service from the logged-in user's shop catalog.
    Past bookings that used this service keep their stored service_type
    string and are unaffected.

    UPDATED: settings_controller.delete_service_type() now takes
    current_user (not shop_id) for Activity Log attribution.
    """
    return settings_controller.delete_service_type(db, current_user, service_id)


# --- PROFILE & PASSWORD ROUTES ---

@router.put("/profile", response_model=schemas.ShopProfileResponse)
def update_shop_profile(
    profile_update: schemas.ShopProfileUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update the logged-in user's own shop name, address, and contact email.

    UPDATED: settings_controller.update_shop_profile() now takes
    current_user (not shop_id) for Activity Log attribution.
    """
    updated_shop = settings_controller.update_shop_profile(db, current_user, profile_update)
    if not updated_shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return updated_shop


@router.put("/password")
def update_password(
    password_update: schemas.PasswordUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update the CURRENTLY LOGGED-IN user's own password after verifying
    their current password.

    NOTE: settings_controller.update_user_password() signature is
    UNCHANGED (still user_id, not current_user) — password changes are
    intentionally NOT written to the Activity Log for privacy reasons.
    """
    result = settings_controller.update_user_password(db, current_user.id, password_update)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result