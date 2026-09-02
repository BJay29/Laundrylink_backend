from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import (
    BookingCreate, BookingResponse, BookingStatusUpdate, BookingAssignMachine,
    CustomerBookingCreate, BookingDecisionResponse, BookingDeclineRequest
)
from app.controller import booking_controller
from app import models
from app.security import get_current_user, get_current_customer

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
    the shop's configured minimum_weight_kg. This endpoint is for
    Service Terminal (staff) bookings only — see POST /bookings/customer
    for customer-initiated bookings from the mobile app.
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
    Does NOT include "Awaiting Approval" bookings — see GET
    /bookings/awaiting-approval for those.

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


# =========================================================
# CUSTOMER (MOBILE APP) BOOKING ENDPOINTS
# =========================================================

@router.post("/customer", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_customer_booking(
    booking_data: CustomerBookingCreate,
    current_customer: models.Customer = Depends(get_current_customer),  # ⬅️ galing sa customer JWT
    db: Session = Depends(get_db)
):
    """
    Creates a booking initiated by a customer via the mobile app.
    Starts as status "Awaiting Approval" — the shop must Accept or
    Decline it (see the two endpoints below) before it behaves like a
    normal Service Terminal booking. Broadcasts a real-time WebSocket
    notification to the shop's connected Service Terminal on success.
    """
    return await booking_controller.create_customer_booking(db, current_customer, booking_data)


@router.get("/awaiting-approval", response_model=List[BookingResponse])
def get_awaiting_approval_bookings(
    current_user: models.User = Depends(get_current_user),  # ⬅️ galing sa JWT
    db: Session = Depends(get_db)
):
    """
    Returns customer-submitted bookings still awaiting Accept/Decline.
    Backs the notification panel on the Service Terminal — used both
    for the initial page load AND as a fallback if the WebSocket
    connection was ever missed/dropped (poll-on-demand, e.g. on refresh).
    """
    return booking_controller.get_awaiting_approval_bookings(db, current_user.shop_id)


@router.patch("/{booking_id}/accept", response_model=BookingResponse)
def accept_customer_booking(
    booking_id: int,
    current_user: models.User = Depends(get_current_user),  # ⬅️ galing sa JWT
    db: Session = Depends(get_db)
):
    """
    Accepts a customer-submitted booking request — moves it from
    "Awaiting Approval" to "Pending", after which it appears in the
    normal Service Terminal list and can be assigned a machine.
    """
    return booking_controller.accept_customer_booking(db, booking_id, current_user)


@router.patch("/{booking_id}/decline", response_model=BookingResponse)
def decline_customer_booking(
    booking_id: int,
    decline_data: BookingDeclineRequest,
    current_user: models.User = Depends(get_current_user),  # ⬅️ galing sa JWT
    db: Session = Depends(get_db)
):
    """
    Declines a customer-submitted booking request — moves it to
    "Declined". Stays in the database for history but never appears in
    the Service Terminal's active bookings list.

    UPDATED: now requires a JSON body with a `reason` (see
    BookingDeclineRequest) — the Service Terminal offers quick presets
    ("Fully booked", "Closed for the day", "Service unavailable") plus a
    free-text option. The reason is saved onto the booking so the
    customer can see it on their end.
    """
    return booking_controller.decline_customer_booking(
        db, booking_id, decline_data.reason, current_user
    )