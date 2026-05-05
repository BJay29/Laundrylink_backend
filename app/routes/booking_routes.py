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
    Links the transaction to specific machines and triggers 'Busy' status 
    in the Machine Hub and Monitoring Dashboard.
    """
    # Using hardcoded shop_id (1) for development/testing
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
    Returns all non-claimed bookings.
    Populates the Service Terminal table and the Dashboard monitoring list.
    Includes nested machine data for 'W#' or 'D#' labeling.
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
    Updates the workflow lifecycle (e.g., In Progress -> Ready -> Claimed).
    Releases assigned machines to 'Available' when status is 'Ready' or 'Claimed'.
    """
    shop_id = 1
    # Updated to match the function name in booking_controller.py
    return booking_controller.update_booking_status(
        db=db, 
        booking_id=booking_id, 
        new_status=new_status, 
        shop_id=shop_id
    )