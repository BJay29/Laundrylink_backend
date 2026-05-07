from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import BookingCreate, BookingResponse, BookingStatusUpdate
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
    Triggers the PredictionService to set hardware status to 'Busy' 
    and increments cycle counts (+1) to track independent resource costs.
    """
    # Currently hardcoded for the development phase at Naga College Foundation.
    # To be replaced with JWT-based shop_id in the production build.
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
    Retrieves all bookings with status other than 'Claimed' or 'Cancelled'.
    Used to populate the 'Service Terminal' and the real-time 'Machine Hub' 
    telemetry for monitoring current hardware load.
    """
    shop_id = 1
    return booking_controller.get_active_bookings(db=db, shop_id=shop_id)

@router.patch("/{booking_id}/status", response_model=BookingResponse)
def update_booking_status(
    booking_id: int,
    status_update: BookingStatusUpdate,
    db: Session = Depends(get_db)
):
    """
    Updates the transaction lifecycle (e.g., In Progress -> Ready -> Claimed).
    When 'Claimed' is triggered, the controller logic invokes the PredictionService 
    to release the assigned Washer/Dryer back to 'Available' status.
    """
    shop_id = 1
    new_status = status_update.status
    
    # Strict validation of the operational state machine
    valid_statuses = ["Pending", "In Progress", "Ready", "Claimed", "Cancelled"]
    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid operational status. Valid options: {', '.join(valid_statuses)}"
        )

    return booking_controller.update_booking_status(
        db=db, 
        booking_id=booking_id, 
        new_status=new_status, 
        shop_id=shop_id
    )

@router.get("/history", response_model=List[BookingResponse])
def read_booking_history(
    db: Session = Depends(get_db)
):
    """
    Retrieves completed transactions (Claimed). 
    This data drives the 'Daily Gross Revenue' and 'Income Forecast' 
    metrics visible on the Dashboard.
    """
    shop_id = 1
    return booking_controller.get_booking_history(db=db, shop_id=shop_id)