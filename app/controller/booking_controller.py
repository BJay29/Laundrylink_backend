from sqlalchemy.orm import Session
from app.models import Booking, Machine
from app.schemas import BookingCreate
from fastapi import HTTPException, status

def create_booking(db: Session, booking_data: BookingCreate, shop_id: int):
    """
    Handles the creation of a new laundry transaction.
    Updated to increment machine cycles and respect maintenance status.
    """
    
    # 1. Create the Booking instance
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
        status="Pending",  
        shop_id=shop_id
    )

    # 2. Handle Machine Assignment & Logic
    # We collect IDs for both washer and dryer if provided in the modal
    assigned_machine_ids = []
    if booking_data.selected_washer_id:
        assigned_machine_ids.append(booking_data.selected_washer_id)
    if booking_data.selected_dryer_id:
        assigned_machine_ids.append(booking_data.selected_dryer_id)

    for m_id in assigned_machine_ids:
        machine = db.query(Machine).filter(Machine.id == m_id, Machine.shop_id == shop_id).first()
        
        if machine:
            # CRITICAL CHECK: Block assignment if machine is under maintenance or unavailable
            if not machine.is_available or machine.status == "Maintenance":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{machine.machine_type} {machine.machine_number} is under maintenance and cannot be used."
                )

            if machine.status != "Available":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Machine {machine.machine_number} is currently {machine.status}"
                )

            # Update machine status to reflect in Real-time Machine Monitoring Hub
            machine.status = "Active" # Or specifically "Washing"/"Drying"
            
            # Increment cycles to update the profitability progress bar
            machine.total_cycles += 1
            
            # Link the machine to the booking (using the first selected machine as primary)
            if not new_booking.machine_id:
                new_booking.machine_id = machine.id

    db.add(new_booking)
    db.commit()
    db.refresh(new_booking)
    return new_booking

def get_active_bookings(db: Session, shop_id: int):
    """
    Retrieves all bookings that are not yet 'Claimed'.
    Used to populate the Service Terminal list.
    """
    return db.query(Booking).filter(
        Booking.shop_id == shop_id, 
        Booking.status != "Claimed"
    ).order_by(Booking.created_at.desc()).all()

def update_status(db: Session, booking_id: int, new_status: str, shop_id: int):
    """
    Updates the status of a booking.
    Releases the machine back to 'Available' once service is complete.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id, Booking.shop_id == shop_id).first()
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    booking.status = new_status

    # Logic: If the laundry is done, set the machine back to 'Available' 
    # unless it was flagged for maintenance during the cycle
    if new_status in ["Ready", "Claimed"] and booking.machine_id:
        machine = db.query(Machine).filter(Machine.id == booking.machine_id).first()
        if machine and machine.status != "Maintenance":
            machine.status = "Available"

    db.commit()
    db.refresh(booking)
    return booking