from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from typing import List
from ..database import get_db
from .. import schemas, models
from ..controller import settings_controller
from ..security import get_current_user

router = APIRouter(
    prefix="/addons",
    tags=["Add-Ons"]
)


@router.get("/", response_model=List[schemas.AddOnResponse])
def list_add_ons(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lists all add-ons (active and inactive) configured for the logged-in
    user's shop. A brand-new shop returns an empty list until the owner
    adds one.
    """
    return settings_controller.get_add_ons(db, current_user.shop_id)


@router.post("/", response_model=schemas.AddOnResponse, status_code=status.HTTP_201_CREATED)
def add_add_on(
    add_on_data: schemas.AddOnBase,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Adds a new add-on (name + price) to the logged-in user's shop
    catalog. This is how a shop owner populates the add-on checklist
    that appears in the mobile app's booking flow.
    """
    return settings_controller.create_add_on(db, current_user, add_on_data)


@router.put("/{add_on_id}", response_model=schemas.AddOnResponse)
def edit_add_on(
    add_on_id: int,
    add_on_data: schemas.AddOnUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Updates an existing add-on's name, price, or active status. Setting
    is_active=false hides it from new bookings without deleting its
    historical usage record.
    """
    return settings_controller.update_add_on(db, current_user, add_on_id, add_on_data)


@router.delete("/{add_on_id}", status_code=status.HTTP_200_OK)
def remove_add_on(
    add_on_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Permanently removes an add-on from the logged-in user's shop
    catalog. Past bookings that used this add-on keep their
    BookingAddOnUsage snapshot and are unaffected.
    """
    return settings_controller.delete_add_on(db, current_user, add_on_id)