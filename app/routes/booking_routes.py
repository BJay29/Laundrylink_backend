from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import BookingCreate, BookingResponse
from app.controller import booking_controller

# Route definition for the laundry transaction lifecycle
router = APIRouter(
    prefix="/bookings",
    tags=["Bookings"]
)

@router.post("/", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_new_booking(
    booking_in: BookingCreate, 
    db: Session = Depends(get_db)
):
    """
    Endpoint for creating a new laundry transaction.
    This triggers the specific Washer/Dryer status to 'Busy' 
    and increments the cycle count by +1 for independent cost and profit tracking.
    """
    # Currently hardcoded to shop_id 1 for the development phase.
    # In production, this should be retrieved from the authenticated user's token.
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
    Retrieves all bookings that are not yet 'Claimed'.
    This is used to populate the Service Terminal table and 
    the Monitoring Dashboard to view real-time progress for each machine.
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
    Updates the booking status (e.g., In Progress -> Ready -> Claimed).
    Once marked as 'Ready' or 'Claimed', the assigned hardware units 
    automatically revert to 'Available', while cycle counts and profit metrics 
    are preserved in the database for accurate business analytics.
    """
    shop_id = 1
    
    # Ensure the status received from the frontend is valid
    valid_statuses = ["In Progress", "Ready", "Claimed", "Cancelled"]
    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status. Choose from: {', '.join(valid_statuses)}"
        )

    return booking_controller.update_booking_status(
        db=db, 
        booking_id=booking_id, 
        new_status=new_status, 
        shop_id=shop_id
    )