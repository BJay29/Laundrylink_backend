from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import (
    BookingCreate, BookingResponse, BookingStatusUpdate, BookingAssignMachine,
    CustomerBookingCreate, BookingDecisionResponse, BookingDeclineRequest,
    PaymentStatusUpdate, MachineAssignmentInput, MoveLoadToDryerInput,
    PaymentRejectRequest, BookingFinalizePricingRequest
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
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Creates a new laundry booking. No machine → 'Pending'. Machine(s)
    provided inline → 'In Progress' (legacy single-machine path only;
    for multi-load bookings, leave washer_id/dryer_id empty and use
    POST /{id}/assign-machines instead).
    """
    return booking_controller.create_booking(db, booking_data, current_user)


@router.get("/active", response_model=List[BookingResponse])
def get_active_bookings(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns all non-finalized bookings for the Service Terminal
    (excludes Claimed/Cancelled/Awaiting Approval/Declined, AND —
    Weighing feature — Awaiting Weighing/Awaiting Payment, which have
    their own panels/modals instead).
    """
    return booking_controller.get_active_bookings(db, current_user.shop_id)


@router.patch("/{booking_id}/status", response_model=BookingResponse)
def update_status(
    booking_id: int,
    status_data: BookingStatusUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Moves a booking through its lifecycle. Releases machines (legacy
    washer_id/dryer_id AND new per-load BookingMachineAssignment rows)
    back to Available on Ready / Claimed / Cancelled.
    """
    return booking_controller.update_booking_status(
        db, booking_id, status_data.status, current_user
    )


@router.patch("/{booking_id}/assign-machine", response_model=BookingResponse)
def assign_machine(
    booking_id: int,
    assign_data: BookingAssignMachine,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    LEGACY — single washer + single dryer assignment. Kept for backward
    compatibility. Use POST /{id}/assign-machines for new multi-load bookings.
    """
    return booking_controller.assign_machine_to_booking(
        db, booking_id, assign_data, current_user
    )


@router.post("/{booking_id}/assign-machines", response_model=BookingResponse)
def assign_machines(
    booking_id: int,
    assign_data: MachineAssignmentInput,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    NEW — Multi-machine assignment for a Pending booking. Pass exactly
    `booking.loads` machine_ids (one per load). Machine type required
    (washers vs dryers) is resolved server-side from the booking's
    service required_phases. Creates one BookingMachineAssignment row
    per load and sets status to 'In Progress'.
    """
    return booking_controller.assign_machines_to_booking(
        db, booking_id, assign_data, current_user
    )


@router.patch("/{booking_id}/loads/{load_number}/move-to-dryer", response_model=BookingResponse)
def move_load_to_dryer(
    booking_id: int,
    load_number: int,
    move_data: MoveLoadToDryerInput,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    NEW — Moves ONE load from washing to drying, picking the dryer in
    real time (not reserved upfront). Releases that load's washer,
    assigns the given dryer, and starts a new countdown.
    """
    return booking_controller.move_load_to_dryer(
        db, booking_id, load_number, move_data, current_user
    )


@router.patch("/{booking_id}/mark-paid", response_model=BookingResponse)
def mark_paid(
    booking_id: int,
    payment_data: PaymentStatusUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Staff-triggered 'Mark as Paid' for cash/COD bookings, and the
    "Approve" action for GCash/PayMaya bookings sitting at
    'pending_verification'. Manual trigger, no fixed timing.

    UPDATED (Weighing feature): if the booking is currently 'Awaiting
    Payment', marking it paid also auto-routes it to 'Pending', making
    it visible in the Service Terminal for machine assignment.
    """
    return booking_controller.mark_booking_as_paid(
        db, booking_id, payment_data, current_user
    )


@router.patch("/{booking_id}/reject-payment", response_model=BookingResponse)
def reject_payment(
    booking_id: int,
    reject_data: PaymentRejectRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    NEW (Online Payment feature) — Staff-triggered "Reject" action for a
    GCash/PayMaya payment proof sitting at 'pending_verification'.
    Reverts payment_status to 'unpaid' and saves the rejection reason.
    """
    return booking_controller.reject_payment(
        db, booking_id, reject_data.reason, current_user
    )


@router.get("/pending-verification", response_model=List[BookingResponse])
def get_pending_verification_bookings(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    NEW (Online Payment feature) — Returns bookings for this shop whose
    payment_status is 'pending_verification'. Backs the "Pending Payment
    Verification" panel in the Service Terminal.
    """
    return booking_controller.get_pending_verification_bookings(db, current_user.shop_id)


# =========================================================
# WEIGHING / FINALIZE PRICING ENDPOINTS (NEW — Admin Dashboard spec,
# Module B: "Mobile Booking Notification & Pricing Modal")
# =========================================================

@router.get("/awaiting-weighing", response_model=List[BookingResponse])
def get_awaiting_weighing_bookings(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    NEW — Returns accepted mobile bookings for this shop that are
    'Awaiting Weighing' — i.e. not yet weighed/priced by staff. Backs
    the new pricing-modal notification panel in the Service Terminal.
    """
    return booking_controller.get_awaiting_weighing_bookings(db, current_user.shop_id)


@router.patch("/{booking_id}/finalize-pricing", response_model=BookingResponse)
async def finalize_pricing(
    booking_id: int,
    pricing_data: BookingFinalizePricingRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    NEW — Staff submits the actual weighed quantity (+ optional ad-hoc
    add-on charges) for a booking that is 'Awaiting Weighing'. Computes
    and saves the final price, then routes the booking to 'Pending'
    (cash/cod) or 'Awaiting Payment' (gcash/paymaya). Notifies the
    customer and broadcasts a 'booking_price_finalized' event to the
    shop's connected Service Terminal instance(s).
    """
    return await booking_controller.finalize_booking_pricing(
        db, booking_id, pricing_data, current_user
    )


# =========================================================
# CUSTOMER (MOBILE APP) BOOKING ENDPOINTS
# =========================================================

@router.post("/customer", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_customer_booking(
    booking_data: CustomerBookingCreate,
    current_customer: models.Customer = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    Creates a mobile-app customer booking. Starts as 'Awaiting Approval'
    until the shop Accepts/Declines. Broadcasts via WebSocket on success.
    """
    return await booking_controller.create_customer_booking(db, current_customer, booking_data)


@router.get("/mine", response_model=List[BookingResponse])
def get_my_bookings(
    current_customer: models.Customer = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Returns every booking made by the logged-in customer, across all shops, any status."""
    return booking_controller.get_customer_bookings(db, current_customer.id)


@router.get("/awaiting-approval", response_model=List[BookingResponse])
def get_awaiting_approval_bookings(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Returns customer-submitted bookings still awaiting Accept/Decline."""
    return booking_controller.get_awaiting_approval_bookings(db, current_user.shop_id)


@router.patch("/{booking_id}/accept", response_model=BookingResponse)
def accept_customer_booking(
    booking_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Accepts a customer-submitted booking — moves 'Awaiting Approval' to
    'Awaiting Weighing' (Weighing feature: no longer straight to
    'Pending' — staff must finalize the actual weight/price first via
    PATCH /{id}/finalize-pricing).
    """
    return booking_controller.accept_customer_booking(db, booking_id, current_user)


@router.patch("/{booking_id}/decline", response_model=BookingResponse)
def decline_customer_booking(
    booking_id: int,
    decline_data: BookingDeclineRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Declines a customer-submitted booking — moves it to 'Declined' with a required reason."""
    return booking_controller.decline_customer_booking(
        db, booking_id, decline_data.reason, current_user
    )

@router.get("/all", response_model=List[BookingResponse])
def get_all_bookings(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Returns every booking for the logged-in user's shop, any status. Backs Record Sales."""
    return booking_controller.get_all_bookings(db, current_user.shop_id)


@router.patch("/{booking_id}/cancel", response_model=BookingResponse)
async def cancel_customer_booking(
    booking_id: int,
    current_customer: models.Customer = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """Customer cancels their own booking. Only while 'Awaiting Approval' or 'Pending'."""
    return await booking_controller.cancel_customer_booking(db, booking_id, current_customer)