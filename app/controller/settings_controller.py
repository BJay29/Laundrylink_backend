from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from .. import models, schemas
from .activity_controller import log_activity
import logging
import random
import string

# Set up logging to track if the system is falling back to defaults
logger = logging.getLogger(__name__)

# --- SYSTEM CONSTANTS ---
# These are strictly "Factory Defaults" used ONLY for new shop initialization
# or manual resets of OPERATIONAL RATES.
SYSTEM_DEFAULTS = {
    "electricity_rate": 12.0,
    "water_rate": 50.0,
    "supplies_cost_per_load": 10.0,
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
    """
    return SYSTEM_DEFAULTS

def update_settings(db: Session, current_user: models.User, settings_data: schemas.SettingUpdate):
    """
    Updates the business parameters and operational rates in the database.
    """
    shop_id = current_user.shop_id
    db_settings = db.query(models.Setting).filter(models.Setting.shop_id == shop_id).first()
    
    update_data = settings_data.model_dump(exclude_unset=True)

    if not db_settings:
        db_settings = models.Setting(shop_id=shop_id, **update_data)
        db.add(db_settings)
    else:
        for key, value in update_data.items():
            if hasattr(db_settings, key):
                setattr(db_settings, key, value)

    if update_data:
        changed_fields = ", ".join(update_data.keys())
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=f"Changed Optimization Settings ({changed_fields})"
        )

    db.commit()
    db.refresh(db_settings)
    logger.info(f"Settings successfully updated for shop_id {shop_id}.")
    return db_settings

def reset_to_system_defaults(db: Session, current_user: models.User):
    """
    Wipes custom operational rates and reverts the shop's DB record to
    SYSTEM_DEFAULTS.
    """
    shop_id = current_user.shop_id
    db_settings = db.query(models.Setting).filter(models.Setting.shop_id == shop_id).first()
    
    if db_settings:
        for key, value in SYSTEM_DEFAULTS.items():
            if hasattr(db_settings, key):
                setattr(db_settings, key, value)

        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description="Reset Optimization Settings back to factory defaults"
        )

        db.commit()
        db.refresh(db_settings)
        return db_settings
    
    return get_settings(db, shop_id)

def get_pricing_for_booking(db: Session, shop_id: int):
    """
    Crucial helper for the Booking Modal.
    Builds the pricing map dynamically from whatever ServiceType records
    the shop owner has configured.
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

    pricing["detergent_fee"] = float(settings.supplies_cost_per_load)
    pricing["minimum_weight_kg"] = float(settings.minimum_weight_kg or 6.0)

    return pricing

# --- SERVICE TYPE FUNCTIONS ---

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

def create_service_type(db: Session, current_user: models.User, service_data: schemas.ServiceTypeBase):
    """
    Registers a new service (name + price + duration + pricing_unit +
    required_phases) for the shop. Prevents exact duplicate names
    (case-insensitive) for the same shop.

    NEW (multi-machine assignment feature): ini-save na rin ang
    service_data.required_phases ("wash_only" | "dry_only" |
    "full_service") — ginagamit ito ni booking_controller.
    assign_machines_to_booking() para malaman kung washers o dryers
    ang dapat ipakita para sa unang machine assignment ng isang
    booking na gumagamit ng service na ito.
    """
    shop_id = current_user.shop_id

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
        duration_minutes=service_data.duration_minutes,
        pricing_unit=service_data.pricing_unit,
        required_phases=service_data.required_phases,  # NEW
        shop_id=shop_id
    )
    db.add(new_service)
    db.flush()  # kailangan para makuha ang new_service.name bago mag-commit

    log_activity(
        db, shop_id,
        actor_name=current_user.full_name or current_user.email,
        actor_role=current_user.role,
        description=(
            f"Added a new service: {new_service.name} "
            f"(₱{new_service.price} / {new_service.pricing_unit}, {new_service.duration_minutes} min, "
            f"{new_service.required_phases})"
        )
    )

    db.commit()
    db.refresh(new_service)
    return new_service

def update_service_type(db: Session, current_user: models.User, service_id: int, service_data: schemas.ServiceTypeUpdate):
    """
    Edits an existing service's name, price, duration, active status,
    pricing_unit, or required_phases.

    NOTE (multi-machine assignment feature): walang binago dito —
    automatic na kasama na ang required_phases sa generic
    update_data.items() loop sa ibaba, dahil idinagdag na ito bilang
    optional field sa ServiceTypeUpdate schema. Kapag ipinasa ito ng
    client, ma-a-apply na ito nang walang dagdag na code.
    """
    shop_id = current_user.shop_id

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

    service_label = service.name  # kunin bago mabago, para tama sa log kahit napalitan ang pangalan

    for key, value in update_data.items():
        setattr(service, key, value)

    if update_data:
        changed_fields = ", ".join(update_data.keys())
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=f"Updated service: {service_label} ({changed_fields})"
        )

    db.commit()
    db.refresh(service)
    return service

def delete_service_type(db: Session, current_user: models.User, service_id: int):
    """
    Removes a service from the shop's catalog.
    """
    shop_id = current_user.shop_id

    service = (
        db.query(models.ServiceType)
        .filter(models.ServiceType.id == service_id, models.ServiceType.shop_id == shop_id)
        .first()
    )
    if not service:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service type not found.")

    service_name = service.name
    db.delete(service)

    log_activity(
        db, shop_id,
        actor_name=current_user.full_name or current_user.email,
        actor_role=current_user.role,
        description=f"Removed service: {service_name}"
    )

    db.commit()
    return {"message": f"Service '{service_name}' removed successfully."}

# --- ADD-ON FUNCTIONS ---

def get_add_ons(db: Session, shop_id: int):
    """
    Returns all add-ons (active and inactive) configured for a shop.
    """
    return (
        db.query(models.AddOn)
        .filter(models.AddOn.shop_id == shop_id)
        .order_by(models.AddOn.id.asc())
        .all()
    )

def create_add_on(db: Session, current_user: models.User, add_on_data: schemas.AddOnBase):
    """
    Registers a new add-on (name + price) for the shop.
    """
    shop_id = current_user.shop_id

    existing = (
        db.query(models.AddOn)
        .filter(
            models.AddOn.shop_id == shop_id,
            models.AddOn.name.ilike(add_on_data.name)
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"An add-on named '{add_on_data.name}' already exists for this shop."
        )

    new_add_on = models.AddOn(
        name=add_on_data.name,
        price=add_on_data.price,
        is_active=add_on_data.is_active,
        shop_id=shop_id
    )
    db.add(new_add_on)
    db.flush()

    log_activity(
        db, shop_id,
        actor_name=current_user.full_name or current_user.email,
        actor_role=current_user.role,
        description=f"Added a new add-on: {new_add_on.name} (₱{new_add_on.price})"
    )

    db.commit()
    db.refresh(new_add_on)
    return new_add_on

def update_add_on(db: Session, current_user: models.User, add_on_id: int, add_on_data: schemas.AddOnUpdate):
    """Edits an existing add-on's name, price, or active status."""
    shop_id = current_user.shop_id

    add_on = (
        db.query(models.AddOn)
        .filter(models.AddOn.id == add_on_id, models.AddOn.shop_id == shop_id)
        .first()
    )
    if not add_on:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Add-on not found.")

    update_data = add_on_data.model_dump(exclude_unset=True)

    if "name" in update_data:
        duplicate = (
            db.query(models.AddOn)
            .filter(
                models.AddOn.shop_id == shop_id,
                models.AddOn.name.ilike(update_data["name"]),
                models.AddOn.id != add_on_id
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"An add-on named '{update_data['name']}' already exists for this shop."
            )

    add_on_label = add_on.name

    for key, value in update_data.items():
        setattr(add_on, key, value)

    if update_data:
        changed_fields = ", ".join(update_data.keys())
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=f"Updated add-on: {add_on_label} ({changed_fields})"
        )

    db.commit()
    db.refresh(add_on)
    return add_on

def delete_add_on(db: Session, current_user: models.User, add_on_id: int):
    """
    Removes an add-on from the shop's catalog.
    """
    shop_id = current_user.shop_id

    add_on = (
        db.query(models.AddOn)
        .filter(models.AddOn.id == add_on_id, models.AddOn.shop_id == shop_id)
        .first()
    )
    if not add_on:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Add-on not found.")

    add_on_name = add_on.name
    db.delete(add_on)

    log_activity(
        db, shop_id,
        actor_name=current_user.full_name or current_user.email,
        actor_role=current_user.role,
        description=f"Removed add-on: {add_on_name}"
    )

    db.commit()
    return {"message": f"Add-on '{add_on_name}' removed successfully."}

# --- PROMO CODE FUNCTIONS ---

def get_promo_codes(db: Session, shop_id: int):
    """
    Returns all promo codes (active and inactive) configured for a shop.
    """
    return (
        db.query(models.PromoCode)
        .filter(models.PromoCode.shop_id == shop_id)
        .order_by(models.PromoCode.id.desc())
        .all()
    )


def _generate_unique_promo_code(db: Session, shop_id: int, discount_type: str, discount_value: float) -> str:
    """
    Gumagawa ng random na promo code, halimbawa "SAVE20-X7K9"
    (percent discount) o "PROMO150-A3B8" (fixed amount discount).
    """
    prefix = "SAVE" if discount_type == "percent" else "PROMO"
    value_part = str(int(discount_value))

    for _ in range(10):
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        candidate_code = f"{prefix}{value_part}-{suffix}"

        existing = (
            db.query(models.PromoCode)
            .filter(
                models.PromoCode.shop_id == shop_id,
                models.PromoCode.code == candidate_code
            )
            .first()
        )
        if not existing:
            return candidate_code

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Could not generate a unique promo code. Please try again."
    )


def create_promo_code(db: Session, current_user: models.User, promo_data: schemas.PromoCodeGenerateInput):
    """
    Registers a new promo code para sa shop, AUTO-GENERATED ang `code`.
    """
    shop_id = current_user.shop_id

    generated_code = _generate_unique_promo_code(
        db, shop_id, promo_data.discount_type, promo_data.discount_value
    )

    new_promo = models.PromoCode(
        code=generated_code,
        discount_type=promo_data.discount_type,
        discount_value=promo_data.discount_value,
        is_active=promo_data.is_active,
        max_uses=promo_data.max_uses,
        expires_at=promo_data.expires_at,
        shop_id=shop_id
    )
    db.add(new_promo)
    db.flush()

    log_activity(
        db, shop_id,
        actor_name=current_user.full_name or current_user.email,
        actor_role=current_user.role,
        description=(
            f"Generated a new promo code: {new_promo.code} "
            f"({new_promo.discount_value}{'%' if new_promo.discount_type == 'percent' else '₱'} off)"
        )
    )

    db.commit()
    db.refresh(new_promo)
    return new_promo


def update_promo_code(db: Session, current_user: models.User, promo_id: int, promo_data: schemas.PromoCodeUpdate):
    """Edits an existing promo code's details."""
    shop_id = current_user.shop_id

    promo = (
        db.query(models.PromoCode)
        .filter(models.PromoCode.id == promo_id, models.PromoCode.shop_id == shop_id)
        .first()
    )
    if not promo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promo code not found.")

    update_data = promo_data.model_dump(exclude_unset=True)

    if "code" in update_data:
        duplicate = (
            db.query(models.PromoCode)
            .filter(
                models.PromoCode.shop_id == shop_id,
                models.PromoCode.code == update_data["code"],
                models.PromoCode.id != promo_id
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A promo code '{update_data['code']}' already exists for this shop."
            )

    promo_label = promo.code

    for key, value in update_data.items():
        setattr(promo, key, value)

    if update_data:
        changed_fields = ", ".join(update_data.keys())
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=f"Updated promo code: {promo_label} ({changed_fields})"
        )

    db.commit()
    db.refresh(promo)
    return promo

def delete_promo_code(db: Session, current_user: models.User, promo_id: int):
    """Removes a promo code from the shop's catalog."""
    shop_id = current_user.shop_id

    promo = (
        db.query(models.PromoCode)
        .filter(models.PromoCode.id == promo_id, models.PromoCode.shop_id == shop_id)
        .first()
    )
    if not promo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Promo code not found.")

    promo_code = promo.code
    db.delete(promo)

    log_activity(
        db, shop_id,
        actor_name=current_user.full_name or current_user.email,
        actor_role=current_user.role,
        description=f"Removed promo code: {promo_code}"
    )

    db.commit()
    return {"message": f"Promo code '{promo_code}' removed successfully."}

# --- PROFILE FUNCTIONS ---

def update_shop_profile(db: Session, current_user: models.User, profile_data: schemas.ShopProfileUpdate):
    """
    Updates the shop's contact information and business profile.
    """
    shop_id = current_user.shop_id

    db_shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not db_shop:
        return None
    
    update_data = profile_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(db_shop, key):
            setattr(db_shop, key, value)

    if update_data:
        changed_fields = ", ".join(update_data.keys())
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=f"Updated shop profile ({changed_fields})"
        )

    db.commit()
    db.refresh(db_shop)
    return db_shop

# REMOVED (Supabase Auth migration): update_user_password() — dating
# tumatawag sa schemas.PasswordUpdate (tinanggal na) at gumagamit ng
# pwd_context/CryptContext + db_user.hashed_password (wala nang column
# na 'yan sa User model — tinanggal na noong ilipat natin ang password
# storage papunta sa Supabase Auth mismo). Wala nang route na tumatawag
# dito (tinanggal na rin natin ang PUT /settings/password sa
# setting_routes.py), kaya dead code na ito. Ang password change ng
# Owner/Staff ay direktang Supabase Auth SDK na ang bahala
# (client-side supabase.auth.updateUser({ password: newPassword })).
#
# Kasabay nito, tinanggal na rin ang mga import na para lang dito
# ginamit: `from passlib.context import CryptContext` at ang
# `pwd_context = CryptContext(...)` instance.

def get_shop_profile(db: Session, shop_id: int):
    """
    Retrieves the shop's own profile info (name, address, delivery
    settings) for display before editing.
    """
    return db.query(models.Shop).filter(models.Shop.id == shop_id).first()