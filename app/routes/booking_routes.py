from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import BookingCreate, BookingResponse, BookingStatusUpdate, BookingAssignMachine
from app.controller import booking_controller
from app import models
from app.security import get_current_user

# Booking router — handles all laundry transaction lifecycle endpoints
router = APIRouter(
    prefix="/bookings",
    tags=["Bookings"]
)


@router.post("/", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_booking(
    booking_data: BookingCreate,
    current_user: models.User = Depends(get_current_user),  # ⬅️ galing sa JWT
    db: Session = Depends(get_db)
):
    """
    Creates a new laundry booking.
    Machine assignment is optional:
    - No machine provided  → status = 'Pending'
    - Machine(s) provided  → status = 'In Progress', machines marked Busy

    shop_id is now taken from the authenticated user's JWT — NOT from
    booking_data.shop_id in the request body. Even if a client sends a
    different shop_id in the body, it is ignored; the booking is always
    scoped to the logged-in user's own shop.

    The controller validates that booking_data.service_type matches an
    active ServiceType configured by this shop, and that the weight meets
    the shop's configured minimum_weight_kg. Both walk-in (web) and
    mobile app bookings go through this same validation.
    """
    return booking_controller.create_booking(db, booking_data, current_user)


@router.get("/active", response_model=List[BookingResponse])
def get_active_bookings(
    current_user: models.User = Depends(get_current_user),  # ⬅️ galing sa JWT
    db: Session = Depends(get_db)
):
    """
    Returns all non-finalized bookings for the Service Terminal.
    Includes both Pending (no machine assigned) and In Progress bookings.

    shop_id no longer comes from a query parameter — it is derived from
    the logged-in user's JWT, so a user can never query another shop's
    active bookings by editing the URL.

    Read-only — get_active_bookings() still takes a bare shop_id (no
    signature change), so current_user.shop_id is passed directly here.
    """
    return booking_controller.get_active_bookings(db, current_user.shop_id)


@router.patch("/{booking_id}/status", response_model=BookingResponse)
def update_status(
    booking_id: int,
    status_data: BookingStatusUpdate,
    current_user: models.User = Depends(get_current_user),  # ⬅️ galing sa JWT
    db: Session = Depends(get_db)
):
    """
    Moves a booking through its lifecycle:
    Pending → In Progress → Ready → Claimed
    Releases machines back to Available on Ready / Claimed / Cancelled.

    shop_id is derived from the JWT — the controller's existing
    Booking.shop_id == shop_id filter ensures a user can only update
    bookings belonging to their own shop (404 otherwise).

    UPDATED: booking_controller.update_booking_status() now takes
    current_user (not shop_id) so the resulting Activity Log entry can
    attribute this status change to whoever performed it.
    """
    return booking_controller.update_booking_status(
        db, booking_id, status_data.status, current_user
    )


@router.patch("/{booking_id}/assign-machine", response_model=BookingResponse)
def assign_machine(
    booking_id: int,
    assign_data: BookingAssignMachine,
    current_user: models.User = Depends(get_current_user),  # ⬅️ galing sa JWT
    db: Session = Depends(get_db)
):
    """
    Assigns a washer and/or dryer to an existing Pending booking.
    - Validates machines are available and belong to this shop
    - Marks assigned machines as Busy and updates telemetry
    - Transitions booking status: Pending → In Progress
    Called from the Service Terminal when the operator clicks 'Assign Machine'.

    shop_id is derived from the JWT, not a query parameter.

    UPDATED: booking_controller.assign_machine_to_booking() now takes
    current_user (not shop_id) so the resulting Activity Log entry can
    attribute this machine assignment to whoever performed it.
    """
    return booking_controller.assign_machine_to_booking(
        db, booking_id, assign_data, current_user
    )