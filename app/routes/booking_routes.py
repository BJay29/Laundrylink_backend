from fastapi import APIRouter, Depends, status, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import (
    BookingCreate, BookingResponse, BookingStatusUpdate, BookingAssignMachine,
    CustomerBookingCreate, BookingDecisionResponse, BookingDeclineRequest,
    PaymentStatusUpdate, MachineAssignmentInput, MoveLoadToDryerInput,
    PaymentRejectRequest, BookingFinalizePricingRequest, BookingSubmitPaymentProofRequest,
    RiderAssignmentInput, PromoPreviewRequest, PromoPreviewResponse,
)
from app.controller import booking_controller
from app import models
from app.security import get_current_user, get_current_customer, decode_supabase_token
from app.services.customer_ws_manager import customer_manager

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
async def update_status(
    booking_id: int,
    status_data: BookingStatusUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Moves a booking through its lifecycle. Releases machines (legacy
    washer_id/dryer_id AND new per-load BookingMachineAssignment rows)
    back to Available on Ready / Claimed / Cancelled.

    FIXED: booking_controller.update_booking_status() is now `async`
    (it pushes a live WebSocket event to the customer's device) — this
    route must be `async def` and `await` it, or FastAPI would try to
    serialize an unawaited coroutine instead of the actual
    BookingResponse.
    """
    return await booking_controller.update_booking_status(
        db, booking_id, status_data.status, current_user
    )


@router.patch("/{booking_id}/assign-machine", response_model=BookingResponse)
async def assign_machine(
    booking_id: int,
    assign_data: BookingAssignMachine,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    LEGACY — single washer + single dryer assignment. Kept for backward
    compatibility. Use POST /{id}/assign-machines for new multi-load bookings.

    UPDATED (Booking & Order Tracking Flow Fix): booking_controller.
    assign_machine_to_booking() is now `async` (live customer push) —
    route updated to match.
    """
    return await booking_controller.assign_machine_to_booking(
        db, booking_id, assign_data, current_user
    )


@router.post("/{booking_id}/assign-machines", response_model=BookingResponse)
async def assign_machines(
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

    UPDATED (Booking & Order Tracking Flow Fix): booking_controller.
    assign_machines_to_booking() is now `async` (live customer push) —
    route updated to match.
    """
    return await booking_controller.assign_machines_to_booking(
        db, booking_id, assign_data, current_user
    )


@router.patch("/{booking_id}/loads/{load_number}/move-to-dryer", response_model=BookingResponse)
async def move_load_to_dryer(
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

    UPDATED (Booking & Order Tracking Flow Fix): booking_controller.
    move_load_to_dryer() is now `async` (live customer push — this is
    the "Washing → Drying" real-time update the spec calls out) — route
    updated to match.
    """
    return await booking_controller.move_load_to_dryer(
        db, booking_id, load_number, move_data, current_user
    )


@router.patch("/{booking_id}/mark-paid", response_model=BookingResponse)
async def mark_paid(
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

    FIXED: booking_controller.mark_booking_as_paid() is now `async`
    (customer WebSocket push) — route updated to match.
    """
    return await booking_controller.mark_booking_as_paid(
        db, booking_id, payment_data, current_user
    )


@router.patch("/{booking_id}/reject-payment", response_model=BookingResponse)
async def reject_payment(
    booking_id: int,
    reject_data: PaymentRejectRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    NEW (Online Payment feature) — Staff-triggered "Reject" action for a
    GCash/PayMaya payment proof sitting at 'pending_verification'.
    Reverts payment_status to 'unpaid' and saves the rejection reason.

    FIXED: booking_controller.reject_payment() is now `async` (customer
    WebSocket push) — route updated to match.
    """
    return await booking_controller.reject_payment(
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
    customer, broadcasts a 'booking_price_finalized' event to the
    shop's connected Service Terminal instance(s), AND pushes a
    'booking_updated' event straight to the customer's own device.
    """
    return await booking_controller.finalize_booking_pricing(
        db, booking_id, pricing_data, current_user
    )


# =========================================================
# RIDER ASSIGNMENT ENDPOINTS (NEW — Pickup & Delivery feature)
# =========================================================
#
# Manual text-entry lang (rider name + contact number) — walang Rider
# table/model, walang naka-login na rider account. Applicable lang sa
# mga booking na fulfillment_mode == "delivery" (see booking_controller.
# assign_pickup_rider()/assign_delivery_rider() para sa validation).

@router.patch("/{booking_id}/assign-pickup-rider", response_model=BookingResponse)
async def assign_pickup_rider(
    booking_id: int,
    rider_data: RiderAssignmentInput,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    NEW — Staff enters the rider's name and contact number for the
    PICKUP leg of a delivery booking (the rider who will collect dirty
    laundry from the customer's address). Not gated to a single status
    — can be set as soon as the booking is accepted and re-set later if
    the assigned rider changes.

    UPDATED (Booking & Order Tracking Flow Fix): booking_controller.
    assign_pickup_rider() is now `async` (live customer push, matching
    assign_delivery_rider() below) — route updated to match.
    """
    return await booking_controller.assign_pickup_rider(
        db, booking_id, rider_data, current_user
    )


@router.patch("/{booking_id}/assign-delivery-rider", response_model=BookingResponse)
async def assign_delivery_rider(
    booking_id: int,
    rider_data: RiderAssignmentInput,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    NEW — Staff enters the rider's name and contact number for the
    DELIVERY leg of a delivery booking (the rider who will bring the
    clean laundry back to the customer). Allowed while the booking is
    'In Progress' or 'Ready'. Pushes a live 'booking_updated' event to
    the customer's device — this is the "your laundry is on the way"
    signal the mobile app stepper is listening for.
    """
    return await booking_controller.assign_delivery_rider(
        db, booking_id, rider_data, current_user
    )


# =========================================================
# CUSTOMER (MOBILE APP) BOOKING ENDPOINTS
# =========================================================

@router.post("/promo-preview", response_model=PromoPreviewResponse)
def preview_promo_code(
    preview_data: PromoPreviewRequest,
    current_customer: models.Customer = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    NEW (Real-time Promo Preview feature) — mobile app calls this while
    the customer is still typing a promo code in the Booking Form
    (debounced client-side), BEFORE submitting the full booking. Never
    raises for an invalid/expired/exhausted code — returns
    {"valid": false, "message": "..."} instead, so the UI can show a
    calm inline hint rather than a scary error banner mid-typing. Does
    NOT increment PromoCode.times_used — that only happens for a real,
    submitted booking (see POST /bookings/customer below).
    """
    return booking_controller.preview_promo_code(
        db, preview_data.shop_id, preview_data.code, preview_data.subtotal
    )


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
async def accept_customer_booking(
    booking_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Accepts a customer-submitted booking — moves 'Awaiting Approval' to
    'Awaiting Weighing' (Weighing feature: no longer straight to
    'Pending' — staff must finalize the actual weight/price first via
    PATCH /{id}/finalize-pricing).

    UPDATED (Booking & Order Tracking Flow Fix): booking_controller.
    accept_customer_booking() is now `async` (live customer push) —
    route updated to match.
    """
    return await booking_controller.accept_customer_booking(db, booking_id, current_user)


@router.patch("/{booking_id}/decline", response_model=BookingResponse)
async def decline_customer_booking(
    booking_id: int,
    decline_data: BookingDeclineRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Declines a customer-submitted booking — moves it to 'Declined' with a required reason.

    UPDATED (Booking & Order Tracking Flow Fix): booking_controller.
    decline_customer_booking() is now `async` (live customer push) —
    route updated to match.
    """
    return await booking_controller.decline_customer_booking(
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


@router.patch("/{booking_id}/submit-payment-proof", response_model=BookingResponse)
async def submit_payment_proof(
    booking_id: int,
    proof_data: BookingSubmitPaymentProofRequest,
    current_customer: models.Customer = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    NEW (Module C) — mobile app customer attaches proof of payment to
    an already-"Awaiting Payment" booking. Sets payment_status to
    "pending_verification", notifies the shop's Service Terminal, and
    pushes a confirmation back to the customer's own device.
    """
    return await booking_controller.submit_payment_proof(
        db, booking_id, proof_data, current_customer
    )


# =========================================================
# CUSTOMER WEBSOCKET (NEW — live "booking_updated" push channel)
# =========================================================

@router.websocket("/ws/customer")
async def customer_websocket(
    websocket: WebSocket,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """
    Mobile app WebSocket connection — kailangan ipasa ang Supabase JWT
    bilang query param (?token=...) dahil hindi native na sumusuporta
    ang WebSocket protocol sa Authorization headers gaya ng REST.

    Ginagamit ito ng order_tracking_page.dart (o katumbas) bilang
    live-update channel — sa sandaling magbago ang booking status,
    ma-finalize ang presyo, o ma-verify/i-reject ang payment mula sa
    shop, agad na matatanggap ng customer ang "booking_updated" event
    dito (see customer_manager.send_to_customer() calls sa
    booking_controller.py).

    Gumagamit ng normal na Depends(get_db) dito (hindi SessionLocal()
    direkta) dahil available naman ang request-scoped dependency
    injection sa WebSocket route functions sa FastAPI, hindi tulad ng
    ConnectionManager sa ws_manager.py na walang access doon sa
    konteksto kung saan ito ginagamit.
    """
    try:
        claims = decode_supabase_token(token)
    except Exception:
        await websocket.close(code=4401)
        return

    supabase_uid = claims.get("sub")
    customer = db.query(models.Customer).filter(
        models.Customer.supabase_uid == supabase_uid
    ).first()

    if not customer or not customer.is_active:
        await websocket.close(code=4401)
        return

    await customer_manager.connect(customer.id, websocket)

    try:
        while True:
            # Keep the connection alive; the client doesn't need to
            # send anything meaningful — this just waits for a
            # disconnect signal.
            await websocket.receive_text()
    except WebSocketDisconnect:
        customer_manager.disconnect(customer.id, websocket)