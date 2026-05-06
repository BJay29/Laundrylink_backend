from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import BookingCreate, BookingResponse
from app.controller import booking_controller

# Route definition para sa laundry transaction lifecycle
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
    Endpoint para sa paggawa ng bagong laundry transaction.
    Ito ang nagti-trigger para maging 'Busy' ang specific na Washer/Dryer 
    at mag-increment ng +1 sa cycle count nito para sa independent cost tracking.
    """
    # Kasalukuyang naka-hardcoded sa shop_id 1 para sa development phase
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
    Kinukuha ang lahat ng bookings na hindi pa 'Claimed'.
    Ginagamit ito para i-populate ang Service Terminal table at 
    Monitoring Dashboard para makita ang real-time progress ng bawat machine.
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
    Nag-u-update ng status (e.g., In Progress -> Ready -> Claimed).
    Kapag 'Ready' o 'Claimed' na, awtomatikong magiging 'Available' ang machine 
    pero mananatili ang cycle count nito sa database para sa accurate data analytics.
    """
    shop_id = 1
    
    # Siguraduhin na valid ang status na pinapadala mula sa frontend
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