from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import BookingCreate, BookingResponse, BookingStatusUpdate, BookingAssignMachine
from app.controller import booking_controller

# Booking router — handles all laundry transaction lifecycle endpoints
router = APIRouter(
    prefix="/bookings",
    tags=["Bookings"]
)


@router.post("/", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_booking(booking_data: BookingCreate, db: Session = Depends(get_db)):
    """
    Creates a new laundry booking.
    Machine assignment is optional:
    - No machine provided  → status = 'Pending'
    - Machine(s) provided  → status = 'In Progress', machines marked Busy
    """
    shop_id = booking_data.shop_id or 1
    return booking_controller.create_booking(db, booking_data, shop_id)


@router.get("/active", response_model=List[BookingResponse])
def get_active_bookings(db: Session = Depends(get_db)):
    """
    Returns all non-finalized bookings for the Service Terminal.
    Includes both Pending (no machine assigned) and In Progress bookings.
    """
    shop_id = 1
    return booking_controller.get_active_bookings(db, shop_id)


@router.patch("/{booking_id}/status", response_model=BookingResponse)
def update_status(
    booking_id: int,
    status_data: BookingStatusUpdate,
    db: Session = Depends(get_db)
):
    """
    Moves a booking through its lifecycle:
    Pending → In Progress → Ready → Claimed
    Releases machines back to Available on Ready / Claimed / Cancelled.
    """
    shop_id = 1
    return booking_controller.update_booking_status(
        db, booking_id, status_data.status, shop_id
    )


@router.patch("/{booking_id}/assign-machine", response_model=BookingResponse)
def assign_machine(
    booking_id: int,
    assign_data: BookingAssignMachine,
    db: Session = Depends(get_db)
):
    """
    Assigns a washer and/or dryer to an existing Pending booking.
    - Validates machines are available and belong to this shop
    - Marks assigned machines as Busy and updates telemetry
    - Transitions booking status: Pending → In Progress
    Called from the Service Terminal when the operator clicks 'Assign Machine'.
    """
    shop_id = 1
    return booking_controller.assign_machine_to_booking(
        db, booking_id, assign_data, shop_id
    )