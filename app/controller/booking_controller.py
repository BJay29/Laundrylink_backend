from sqlalchemy.orm import Session, joinedload
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
    # washer_id and dryer_id are received from the frontend selection grid.
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
        status="In Progress", # New bookings default to 'In Progress' state
        washer_id=booking_data.washer_id,
        dryer_id=booking_data.dryer_id,
        shop_id=shop_id,
        # Uses UTC now to ensure exact booking time regardless of server location
        created_at=datetime.now(timezone.utc) 
    )

    # 2. Identify hardware to be updated based on the assignment
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

        # Safety Check: Prevent booking if machine is broken or already in use
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

        # Update Machine State for Dashboard Real-time Monitoring
        machine.status = "Busy"
        machine.total_cycles += 1 # Auto-increment performance stats for analytics
        
        # Default countdown (45 mins). Can be adjusted based on service_type in the future.
        machine.remaining_time = 45 

    try:
        db.add(new_booking)
        db.commit()
        # Eagerly load the washer/dryer relationships so they are available in the response
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
    Used to populate the Service Terminal table.
    Uses joinedload to ensure washer/dryer info is included for "W1/D1" labels.
    """
    return db.query(Booking).options(
        joinedload(Booking.washer),
        joinedload(Booking.dryer)
    ).filter(
        Booking.shop_id == shop_id, 
        Booking.status != "Claimed"
    ).order_by(Booking.created_at.desc()).all()

def update_booking_status(db: Session, booking_id: int, new_status: str, shop_id: int):
    """
    Updates a booking's lifecycle (e.g., 'In Progress' -> 'Ready' -> 'Claimed').
    Automatically releases linked machines back to 'Available' once process completes.
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

    # Logic: Release machines once the laundry is finished or claimed
    if new_status in ["Ready", "Claimed"]:
        assigned_ids = [m_id for m_id in [booking.washer_id, booking.dryer_id] if m_id is not None]
        
        if assigned_ids:
            related_machines = db.query(Machine).filter(
                Machine.id.in_(assigned_ids)
            ).all()
            
            for machine in related_machines:
                # Do not revert to Available if unit was manually flagged for Maintenance
                if machine.status != "Maintenance":
                    machine.status = "Available"
                    machine.remaining_time = 0 # Reset countdown on Dashboard UI

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