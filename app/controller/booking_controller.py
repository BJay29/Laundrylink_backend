from sqlalchemy.orm import Session
from app.models import Booking, Machine
from app.schemas import BookingCreate
from fastapi import HTTPException, status
from datetime import datetime, timezone

def create_booking(db: Session, booking_data: BookingCreate, shop_id: int):
    """
    Handles the creation of a new laundry transaction.
    Links the booking to assigned hardware and updates machine states to 'Busy'.
    This ensures synchronization between the Service Terminal and Monitoring Grid.
    """
    
    # 1. Initialize the Booking instance
    # Ang washer_id at dryer_id ay nanggagaling sa selection grid ng iyong frontend modal.
    new_booking = Booking(
        customer_name=booking_data.customer_name,
        service_type=booking_data.service_type,
        category=booking_data.category,
        weight=booking_data.weight,
        loads=booking_data.loads,
        total_price=booking_data.total_price,
        booking_mode=booking_data.booking_mode,
        add_detergent=booking_data.add_detergent,
        add_delivery=booking_data.add_delivery,
        is_rush=booking_data.is_rush,
        status="In Progress", # Ang bagong booking ay diretso sa 'In Progress' state
        washer_id=booking_data.washer_id,
        dryer_id=booking_data.dryer_id,
        shop_id=shop_id,
        created_at=datetime.now(timezone.utc)
    )

    # 2. Identify machines to be updated
    machine_ids = [m_id for m_id in [new_booking.washer_id, new_booking.dryer_id] if m_id is not None]

    # 3. Validate and update machine availability
    for m_id in machine_ids:
        machine = db.query(Machine).filter(
            Machine.id == m_id, 
            Machine.shop_id == shop_id
        ).first()
        
        if not machine:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Machine ID {m_id} not found."
            )

        # Safety Check: Iwasan ang booking kung sira o gamit na ang machine
        if machine.status == "Maintenance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is currently under maintenance."
            )

        if machine.status == "Busy":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is already occupied."
            )

        # Update Machine State para sa Dashboard Real-time Monitoring
        machine.status = "Busy"
        machine.total_cycles += 1 # Auto-increment para sa Machine Hub analytics
        
        # Default countdown (45 mins). Pwedeng i-adjust base sa service_type sa future.
        machine.remaining_time = 45 

    try:
        db.add(new_booking)
        db.commit()
        db.refresh(new_booking)
        return new_booking
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transaction Failed: {str(e)}"
        )

def get_active_bookings(db: Session, shop_id: int):
    """
    Fetches all current laundry orders that are not yet 'Claimed'.
    Ginagamit ito para i-populate ang Service Terminal table.
    """
    return db.query(Booking).filter(
        Booking.shop_id == shop_id, 
        Booking.status != "Claimed"
    ).order_by(Booking.created_at.desc()).all()

def update_booking_status(db: Session, booking_id: int, new_status: str, shop_id: int):
    """
    Updates a booking's lifecycle (e.g., 'In Progress' -> 'Ready' -> 'Claimed').
    Kapag 'Ready' o 'Claimed' na, awtomatikong magiging 'Available' uli ang machines.
    """
    booking = db.query(Booking).filter(
        Booking.id == booking_id, 
        Booking.shop_id == shop_id
    ).first()
    
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Booking record not found."
        )

    booking.status = new_status

    # Logic: Kapag tapos na ang labada, i-release na ang machines
    if new_status in ["Ready", "Claimed"]:
        assigned_ids = [m_id for m_id in [booking.washer_id, booking.dryer_id] if m_id is not None]
        
        if assigned_ids:
            related_machines = db.query(Machine).filter(
                Machine.id.in_(assigned_ids)
            ).all()
            
            for machine in related_machines:
                # Huwag gawing 'Available' kung manual itong nilagay sa 'Maintenance'
                if machine.status != "Maintenance":
                    machine.status = "Available"
                    machine.remaining_time = 0 # Reset countdown sa Dashboard UI

    try:
        db.commit()
        db.refresh(booking)
        return booking
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Status Update Failed: {str(e)}"
        )