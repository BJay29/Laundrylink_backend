from sqlalchemy.orm import Session
from app.models import Booking, Machine
from app.schemas import BookingCreate
from fastapi import HTTPException, status
from datetime import datetime

def create_booking(db: Session, booking_data: BookingCreate, shop_id: int):
    """
    Handles the creation of a new laundry transaction.
    Links the booking to BOTH washer and dryer and updates their status to 'Busy'.
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
        # Assign specific washer and dryer from frontend selection
        washer_id=booking_data.washer_id,
        dryer_id=booking_data.dryer_id,
        shop_id=shop_id,
        created_at=datetime.utcnow()
    )

    # 2. List of machines to process (Washer and/or Dryer)
    machine_ids = []
    if new_booking.washer_id:
        machine_ids.append(new_booking.washer_id)
    if new_booking.dryer_id:
        machine_ids.append(new_booking.dryer_id)

    # 3. Process and Validate each machine
    for m_id in machine_ids:
        machine = db.query(Machine).filter(Machine.id == m_id, Machine.shop_id == shop_id).first()
        
        if not machine:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Machine with ID {m_id} not found."
            )

        # Validation: Wag payagan kung sira o ginagamit pa
        if machine.status == "Maintenance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is under maintenance."
            )

        if machine.status == "Busy":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is currently busy."
            )

        # Update Machine State for Dashboard Real-time monitoring
        machine.status = "Busy"
        machine.total_cycles += 1 # Dagdag sa stats para sa Machine Hub
        
        # Default cycle time (e.g., 45 mins) para sa countdown timer sa frontend
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
            detail=f"Failed to create booking: {str(e)}"
        )

def get_active_bookings(db: Session, shop_id: int):
    """
    Retrieves all bookings that are not yet 'Claimed'.
    Used to populate the Service Terminal and Dashboard Monitoring lists.
    """
    return db.query(Booking).filter(
        Booking.shop_id == shop_id, 
        Booking.status != "Claimed"
    ).order_by(Booking.created_at.desc()).all()

def update_booking_status(db: Session, booking_id: int, new_status: str, shop_id: int):
    """
    Updates the status of a booking (e.g., to 'Ready' or 'Claimed').
    Automatically releases BOTH assigned machines back to 'Available' status.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id, Booking.shop_id == shop_id).first()
    
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Booking transaction not found"
        )

    booking.status = new_status

    # Logic: Kapag tapos na (Ready/Claimed), gawing Available ulit ang mga machines
    if new_status in ["Ready", "Claimed"]:
        # Hanapin ang washer at dryer na naka-link sa booking na ito
        related_machines = db.query(Machine).filter(
            Machine.id.in_([booking.washer_id, booking.dryer_id])
        ).all()
        
        for machine in related_machines:
            # Wag i-reset kung manually nilagay sa Maintenance ng owner
            if machine.status != "Maintenance":
                machine.status = "Available"
                machine.remaining_time = 0 # Patayin ang timer

    db.commit()
    db.refresh(booking)
    return booking