from sqlalchemy.orm import Session
from app.models import Booking, Machine
from app.schemas import BookingCreate
from fastapi import HTTPException, status
from datetime import datetime

def create_booking(db: Session, booking_data: BookingCreate, shop_id: int):
    """
    Handles the creation of a new laundry transaction.
    Links the booking to assigned hardware and updates machine states to 'Busy'.
    """
    
    # 1. Initialize the Booking instance with dual-machine support
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
        status="In Progress",
        # Link specific machines from the frontend selection
        washer_id=booking_data.washer_id,
        dryer_id=booking_data.dryer_id,
        shop_id=shop_id,
        created_at=datetime.utcnow()
    )

    # 2. Identify machines to be updated based on the booking assignment
    machine_ids = []
    if new_booking.washer_id:
        machine_ids.append(new_booking.washer_id)
    if new_booking.dryer_id:
        machine_ids.append(new_booking.dryer_id)

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

        # Safety Check: Prevent booking if the machine is already in use or broken
        if machine.status == "Maintenance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is currently under maintenance."
            )

        if machine.status == "Busy":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is already occupied by another booking."
            )

        # Update Machine State for Dashboard and Machine Hub synchronization
        machine.status = "Busy"
        machine.total_cycles += 1 # Increment performance stats
        
        # Set default countdown time (e.g., 45 mins) for real-time monitoring
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
    Populates the Service Terminal table and the Dashboard monitoring list.
    """
    return db.query(Booking).filter(
        Booking.shop_id == shop_id, 
        Booking.status != "Claimed"
    ).order_by(Booking.created_at.desc()).all()

def update_booking_status(db: Session, booking_id: int, new_status: str, shop_id: int):
    """
    Updates a booking's lifecycle (e.g., 'In Progress' -> 'Ready' -> 'Claimed').
    Automatically releases linked machines back to 'Available' once the process is complete.
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

    # Logic: If the laundry is finished or claimed, free the machines for next use
    if new_status in ["Ready", "Claimed"]:
        # Query assigned hardware linked to this specific booking
        assigned_ids = [id for id in [booking.washer_id, booking.dryer_id] if id is not None]
        
        if assigned_ids:
            related_machines = db.query(Machine).filter(
                Machine.id.in_(assigned_ids)
            ).all()
            
            for machine in related_machines:
                # Do not revert to Available if the unit was manually flagged for Maintenance
                if machine.status != "Maintenance":
                    machine.status = "Available"
                    machine.remaining_time = 0 # Reset monitoring timer

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