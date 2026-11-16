from fastapi import APIRouter, Depends, Query
from typing import List
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.schemas import RiderJobResponse, RiderDeliveredInput
from app.controller import rider_controller
from app.security import require_role

# Rider router — lahat ng endpoint dito ay para sa naka-login na RIDER lang.
# (Ang rider ay hinaharangan sa lahat ng ibang endpoint — see security.py.)
router = APIRouter(
    prefix="/rider",
    tags=["Rider"]
)


@router.get("/jobs", response_model=List[RiderJobResponse])
def get_my_jobs(
    scope: str = Query("active", pattern="^(active|done)$"),
    current_user: models.User = Depends(require_role("rider")),
    db: Session = Depends(get_db),
):
    """Mga job na naka-assign sa akin. scope=active (default) o done."""
    return rider_controller.get_jobs(db, current_user, scope)


@router.post("/jobs/{booking_id}/picked-up")
async def picked_up(
    booking_id: int,
    current_user: models.User = Depends(require_role("rider")),
    db: Session = Depends(get_db),
):
    """Pickup leg: nakuha ko na ang maruming damit sa customer."""
    return await rider_controller.mark_picked_up(db, current_user, booking_id)


@router.post("/jobs/{booking_id}/start-delivery")
async def start_delivery(
    booking_id: int,
    current_user: models.User = Depends(require_role("rider")),
    db: Session = Depends(get_db),
):
    """Delivery leg: umalis na ako dala ang laundry (Ready → Out for Delivery)."""
    return await rider_controller.start_delivery(db, current_user, booking_id)


@router.post("/jobs/{booking_id}/delivered")
async def delivered(
    booking_id: int,
    data: RiderDeliveredInput,
    current_user: models.User = Depends(require_role("rider")),
    db: Session = Depends(get_db),
):
    """Delivery leg: naihatid na (Out for Delivery → Claimed). May cash_collected kung COD."""
    return await rider_controller.mark_delivered(db, current_user, booking_id, data)