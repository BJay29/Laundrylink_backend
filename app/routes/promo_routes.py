from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from .. import schemas, models
from ..controller import settings_controller
from ..security import get_current_user

router = APIRouter(
    prefix="/promo-codes",
    tags=["Promo Codes"]
)


@router.get("/", response_model=List[schemas.PromoCodeResponse])
def list_promo_codes(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lists all promo codes (active and inactive) configured for the
    logged-in user's shop.
    """
    return settings_controller.get_promo_codes(db, current_user.shop_id)


@router.post("/", response_model=schemas.PromoCodeResponse, status_code=status.HTTP_201_CREATED)
def add_promo_code(
    promo_data: schemas.PromoCodeBase,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Adds a new promo/discount code to the logged-in user's shop.
    discount_type is "percent" or "fixed"; max_uses and expires_at are
    optional limits.
    """
    return settings_controller.create_promo_code(db, current_user, promo_data)


@router.put("/{promo_id}", response_model=schemas.PromoCodeResponse)
def edit_promo_code(
    promo_id: int,
    promo_data: schemas.PromoCodeUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Updates an existing promo code's details. Setting is_active=false
    disables it immediately without deleting its usage history.
    """
    return settings_controller.update_promo_code(db, current_user, promo_id, promo_data)


@router.delete("/{promo_id}", status_code=status.HTTP_200_OK)
def remove_promo_code(
    promo_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Permanently removes a promo code from the logged-in user's shop."""
    return settings_controller.delete_promo_code(db, current_user, promo_id)