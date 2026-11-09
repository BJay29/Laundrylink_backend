from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import BlockedDateCreate, BlockedDateResponse, BlockedDatePublic
from app.controller import blocked_date_controller
from app import models
from app.security import get_current_user, get_current_customer

# "Fully Booked" dates — pinipili ng shop (owner/staff) sa web, at
# hindi na mapipili ng customer sa mobile booking form.
router = APIRouter(
    prefix="/blocked-dates",
    tags=["Blocked Dates"]
)


@router.get("/", response_model=List[BlockedDateResponse])
def list_my_blocked_dates(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Staff/owner: mga upcoming na fully booked na petsa ng sarili nilang shop."""
    return blocked_date_controller.list_blocked_dates(db, current_user.shop_id)


@router.post("/", response_model=BlockedDateResponse, status_code=status.HTTP_201_CREATED)
def add_blocked_date(
    data: BlockedDateCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Staff/owner: markahan ang isang petsa bilang fully booked."""
    return blocked_date_controller.add_blocked_date(db, current_user, data)


@router.delete("/{blocked_id}")
def remove_blocked_date(
    blocked_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Staff/owner: buksan ulit ang petsa para sa bookings."""
    return blocked_date_controller.remove_blocked_date(db, current_user, blocked_id)


@router.get("/shop/{shop_id}", response_model=List[BlockedDatePublic])
def get_shop_blocked_dates(
    shop_id: int,
    current_customer: models.Customer = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    Customer (mobile app): mga petsang fully booked ng isang shop, para
    i-disable sa date picker ng booking form at ng edit booking.
    """
    return blocked_date_controller.get_public_blocked_dates(db, shop_id)