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
    Creates a new laundry booking (Service Terminal / staff only).
    """
    return booking_controller.create_booking(db, booking_data, current_user)


@router.get("/active", response_model=List[BookingResponse])
def get_active_bookings(
    current_user: models.User = Depends(get_current_user),  # ⬅️ galing sa JWT
    db: Session = Depends(get_db)
):
    """
    Returns all non-finalized bookings for the Service Terminal.
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
    """
    return await booking_controller.create_customer_booking(db, current_customer, booking_data)


@router.get("/mine", response_model=List[BookingResponse])
def get_my_bookings(
    current_customer: models.Customer = Depends(get_current_customer),  # ⬅️ galing sa customer JWT
    db: Session = Depends(get_db)
):
    """
    NEW — Returns ALL bookings made by the currently logged-in customer
    (any shop, any status — Awaiting Approval, Pending, In Progress,
    Ready, Claimed, Cancelled, Declined), most recent first.

    Backs the mobile app's Booking Page (booking history + live
    tracking) and Notifications Page. Both screens poll this endpoint
    periodically (in-app only, while the app is open — no push
    notifications yet) to detect status changes made by the shop from
    the web dashboard (accept/decline, In Progress → Ready → Claimed,
    atbp.).
    """
    return booking_controller.get_customer_bookings(db, current_customer.id)


@router.get("/awaiting-approval", response_model=List[BookingResponse])
def get_awaiting_approval_bookings(
    current_user: models.User = Depends(get_current_user),  # ⬅️ galing sa JWT
    db: Session = Depends(get_db)
):
    """
    Returns customer-submitted bookings still awaiting Accept/Decline.
    """
    return booking_controller.get_awaiting_approval_bookings(db, current_user.shop_id)


@router.patch("/{booking_id}/accept", response_model=BookingResponse)
def accept_customer_booking(
    booking_id: int,
    current_user: models.User = Depends(get_current_user),  # ⬅️ galing sa JWT
    db: Session = Depends(get_db)
):
    """
    Accepts a customer-submitted booking request.
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
    Declines a customer-submitted booking request.
    """
    return booking_controller.decline_customer_booking(
        db, booking_id, decline_data.reason, current_user
    )