from sqlalchemy.orm import Session
from app.models import Booking, Machine
from app.schemas import BookingCreate
from fastapi import HTTPException, status
from datetime import datetime

def create_booking(db: Session, booking_data: BookingCreate, shop_id: int):
    """
    Handles the creation of a new laundry transaction.
    Links the booking to machines and updates their status to 'Active' for real-time monitoring.
    """
    
    # 1. Initialize the Booking instance
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
        status="In Progress", # Set to In Progress immediately if machines are assigned
        shop_id=shop_id,
        created_at=datetime.utcnow()
    )

    # 2. Collect Machine IDs from the request (Washer and/or Dryer)
    assigned_machine_ids = []
    if hasattr(booking_data, 'selected_washer_id') and booking_data.selected_washer_id:
        assigned_machine_ids.append(booking_data.selected_washer_id)
    if hasattr(booking_data, 'selected_dryer_id') and booking_data.selected_dryer_id:
        assigned_machine_ids.append(booking_data.selected_dryer_id)

    # 3. Process each assigned machine
    for m_id in assigned_machine_ids:
        machine = db.query(Machine).filter(Machine.id == m_id, Machine.shop_id == shop_id).first()
        
        if not machine:
            continue

        # Validation: Block if machine is not usable
        if machine.status == "Maintenance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is under maintenance."
            )

        if machine.status == "Active":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is already in use."
            )

        # Update Machine State for Dashboard Monitoring
        machine.status = "Active"
        machine.total_cycles += 1 # Increment cycle for profitability tracking
        
        # Calculate an estimated remaining time (e.g., 45 mins default)
        # This will be picked up by the frontend countdown timer
        machine.remaining_time = 45 

        # Link the first machine as the primary reference for the booking
        if not new_booking.machine_id:
            new_booking.machine_id = machine.id

    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)
    return new_booking

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
    Automatically releases the assigned machine back to 'Available' status.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id, Booking.shop_id == shop_id).first()
    
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Booking transaction not found"
        )

    booking.status = new_status

    # Logic: Release machine once the service reaches completion stages
    if new_status in ["Ready", "Claimed"] and booking.machine_id:
        # Find the machine associated with this booking
        machine = db.query(Machine).filter(Machine.id == booking.machine_id).first()
        
        if machine:
            # Only set back to Available if it's not flagged for Maintenance
            if machine.status != "Maintenance":
                machine.status = "Available"
                machine.remaining_time = 0 # Reset timer

    db.commit()
    db.refresh(booking)
    return booking