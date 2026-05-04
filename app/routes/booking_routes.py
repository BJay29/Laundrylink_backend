from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import BookingCreate, BookingResponse
from app.controller import booking_controller
# Assuming you have an auth middleware to get the current user/shop
# from app.utils.auth import get_current_user 

router = APIRouter(
    prefix="/bookings",
    tags=["Bookings"]
)

@router.post("/", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_new_booking(
    booking_in: BookingCreate, 
    db: Session = Depends(get_db),
    # current_user = Depends(get_current_user) # To be enabled once auth is ready
):
    """
    Endpoint to create a new laundry booking.
    Triggers machine status updates if machines are assigned.
    """
    # For now, we use a hardcoded shop_id (1) until your Auth is fully linked
    shop_id = 1 
    
    return booking_controller.create_booking(
        db=db, 
        booking_data=booking_in, 
        shop_id=shop_id
    )

@router.get("/active", response_model=List[BookingResponse])
def read_active_bookings(
    db: Session = Depends(get_db)
):
    """
    Returns all non-claimed bookings for the Service Terminal.
    """
    shop_id = 1
    return booking_controller.get_active_bookings(db=db, shop_id=shop_id)

@router.patch("/{booking_id}/status", response_model=BookingResponse)
def update_booking_status(
    booking_id: int,
    new_status: str,
    db: Session = Depends(get_db)
):
    """
    Updates the progress of a booking (e.g., Pending -> Washing -> Ready).
    """
    shop_id = 1
    return booking_controller.update_status(
        db=db, 
        booking_id=booking_id, 
        new_status=new_status, 
        shop_id=shop_id
    )