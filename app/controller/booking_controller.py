from sqlalchemy.orm import Session, joinedload
from app.models import Booking, Machine
from app.schemas import BookingCreate
from fastapi import HTTPException, status
from datetime import datetime, timezone

def create_booking(db: Session, booking_data: BookingCreate, shop_id: int):
    """
    Creates a new laundry transaction.
    Triggers automatic status updates for assigned machines.
    """

    # 1. Initialize new booking object
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
        washer_id=booking_data.washer_id,
        dryer_id=booking_data.dryer_id,
        shop_id=shop_id,
        created_at=datetime.now(timezone.utc)
    )

    # 2. Collect assigned machine IDs for validation & update
    machine_ids = [
        m_id for m_id in [booking_data.washer_id, booking_data.dryer_id]
        if m_id is not None
    ]

    # 3. Validate and update machine statuses real-time
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
        
        if machine.status == "Maintenance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is under maintenance."
            )
        
        # Security check: baka may naka-unang mag-book habang bukas ang modal
        if machine.status == "Busy":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is already in use."
            )

        # TRIGGER: Update Machine Hub & Monitoring Grid
        machine.status = "Busy"
        machine.total_cycles += 1
        
        # Smart Time Estimation base sa loads o weight
        # 45 mins base time + 5 mins per extra load
        estimated_time = 45 + (max(0, booking_data.loads - 1) * 5)
        machine.remaining_time = estimated_time

    try:
        db.add(new_booking)
        db.commit()

        # RE-FETCH WITH JOINEDLOAD: 
        # Para makuha ang nested objects (washer.machine_number) para sa Service Terminal UI
        result = (
            db.query(Booking)
            .options(
                joinedload(Booking.washer),
                joinedload(Booking.dryer)
            )
            .filter(Booking.id == new_booking.id)
            .first()
        )
        return result

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transaction Failed: {str(e)}"
        )


def get_active_bookings(db: Session, shop_id: int):
    """
    Fetches all non-Claimed bookings with full machine details.
    """
    return (
        db.query(Booking)
        .options(
            joinedload(Booking.washer),
            joinedload(Booking.dryer)
        )
        .filter(
            Booking.shop_id == shop_id,
            Booking.status != "Claimed"
        )
        .order_by(Booking.created_at.desc())
        .all()
    )


def update_booking_status(db: Session, booking_id: int, new_status: str, shop_id: int):
    """
    Handles the booking lifecycle and releases machines back to 'Available'.
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

    # Update logic
    old_status = booking.status
    booking.status = new_status

    # RELEASE LOGIC: Kapag tapos na o kinuha na, bakantehin ang machine
    if new_status in ["Ready", "Claimed"]:
        assigned_ids = [
            m_id for m_id in [booking.washer_id, booking.dryer_id]
            if m_id is not None
        ]

        if assigned_ids:
            related_machines = db.query(Machine).filter(
                Machine.id.in_(assigned_ids)
            ).all()

            for machine in related_machines:
                # Huwag galawin kung naka-maintenance mode ang machine
                if machine.status != "Maintenance":
                    machine.status = "Available"
                    machine.remaining_time = 0

    try:
        db.commit()

        # Re-fetch with joinedload para hindi mag-flicker o mawala ang data sa UI
        result = (
            db.query(Booking)
            .options(
                joinedload(Booking.washer),
                joinedload(Booking.dryer)
            )
            .filter(Booking.id == booking_id)
            .first()
        )
        return result

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Status Update Failed: {str(e)}"
        )