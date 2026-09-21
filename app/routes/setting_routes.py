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


def _build_shop_profile_response(shop: models.Shop, user: models.User) -> schemas.ShopProfileResponse:
    """
    SINGLE SOURCE OF TRUTH for building a ShopProfileResponse.

    Ginagamit ng PAREHONG GET /settings/profile at PUT /settings/profile.

    BAKIT MAY HELPER: dati, hiwalay na ginagawa ang response sa bawat
    endpoint, at paulit-ulit na nakakalimutan ang mga bagong field.
    Una, ang gcash_qr_url/paymaya_qr_url (nawawala ang QR preview pag
    nag-refresh). Ngayon naman, ang accepts_cash / accepts_cod /
    accepts_online — kaya nagre-revert sa OFF ang "Online Payment"
    toggle pag nag-refresh o nag-navigate: na-save naman ito sa DB, pero
    hindi ito kasama sa response, kaya ang frontend ay laging nakakakuha
    ng default (`accepts_online ?? false`) galing sa GET /profile.

    Kapag may bagong Shop field na kailangan ng frontend, dito na lang
    idagdag — isang lugar lang.

    NOTE: email ay galing sa User (Owner/Staff), hindi sa Shop — walang
    `email` column ang Shop model.

    NOTE (null-safety): ang mga lumang Shop row (bago idinagdag ang
    payment columns) ay maaaring NULL ang accepts_*. Ang cash ay
    default na True; ang cod/online ay default na False.
    """
    return schemas.ShopProfileResponse(
        shop_name=shop.shop_name,
        address=shop.address or "",
        email=user.email,
        has_delivery=shop.has_delivery,
        delivery_fee=shop.delivery_fee,
        latitude=shop.latitude,
        longitude=shop.longitude,
        gcash_qr_url=shop.gcash_qr_url,
        paymaya_qr_url=shop.paymaya_qr_url,
        accepts_cash=True if shop.accepts_cash is None else bool(shop.accepts_cash),
        accepts_cod=bool(shop.accepts_cod),
        accepts_online=bool(shop.accepts_online),
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
    Adds a new service (name, price, required phases, and per-phase washer/
    dryer durations) to the logged-in user's shop catalog. This is how a
    shop owner populates the Service Type dropdown that appears in the
    Create Booking modal.

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


# --- PROFILE ROUTES ---

@router.get("/profile", response_model=schemas.ShopProfileResponse)
def get_shop_profile(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Fetch the logged-in user's own shop profile, including delivery
    settings, payment-method flags, and payment QR codes.

    HISTORY OF FIXES (lahat ay iisang klase ng bug — nawawalang field sa
    manual-built response):
      - email: walang `email` column ang Shop; galing ito sa
        current_user.
      - gcash_qr_url / paymaya_qr_url: dating hindi kasama, kaya
        nawawala ang QR preview pag nag-refresh.
      - accepts_cash / accepts_cod / accepts_online: dating hindi
        kasama, kaya nagre-revert sa OFF ang toggle sa Optimization
        Settings pagkatapos mag-refresh o mag-navigate.
    Lahat ito ay hawak na ng _build_shop_profile_response() sa itaas.
    """
    shop = settings_controller.get_shop_profile(db, current_user.shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return _build_shop_profile_response(shop, current_user)


@router.put("/profile", response_model=schemas.ShopProfileResponse)
def update_shop_profile(
    profile_update: schemas.ShopProfileUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update the logged-in user's own shop name, address, delivery
    settings, payment-method flags, and payment QR codes.

    NOTE: email is intentionally NOT part of this update — it's the
    User's own login email, not a Shop field, and is not editable from
    here (see ShopProfileUpdate in schemas.py). The response still
    includes current_user.email so the frontend has it to display.

    Ang response ay ginagawa ng parehong _build_shop_profile_response()
    na ginagamit ng GET, para laging pareho ang hugis ng data.

    UPDATED: settings_controller.update_shop_profile() now takes
    current_user (not shop_id) for Activity Log attribution.
    """
    updated_shop = settings_controller.update_shop_profile(db, current_user, profile_update)
    if not updated_shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return _build_shop_profile_response(updated_shop, current_user)


# REMOVED (Supabase Auth migration): PUT /settings/password — dating
# tumatawag sa schemas.PasswordUpdate (na tinanggal na noong ginawa
# nating Supabase migration, dahil ang password storage/verification
# ay hawak na ng Supabase Auth mismo). Ito ang katapat sa Owner/Staff
# side ng PUT /customer/password na tinanggal din natin sa
# customer_auth_routes.py.
#
# Ang password change ng Owner/Staff (React web app) ay gagawin na
# lang DIREKTA gamit ang Supabase Auth SDK (JS) sa frontend:
#   const { data, error } = await supabase.auth.updateUser({
#     password: newPassword
#   });
#
# (Katulad ng ginawa natin sa Flutter side —
# CustomerService.changePassword() — kung saan muna nire-verify ang
# current password via signInWithPassword() bago tumawag ng
# updateUser(), para hindi lang basta-basta ma-update ang password
# nang walang pag-confirm sa luma.)