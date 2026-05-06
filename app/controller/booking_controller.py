from sqlalchemy.orm import Session, joinedload
from app.models import Booking, Machine
from app.schemas import BookingCreate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status
from datetime import datetime, timezone

def create_booking(db: Session, booking_data: BookingCreate, shop_id: int):
    """
    Creates a new laundry transaction and updates machine cumulative metrics.
    Independent Tracking: Only the selected washer/dryer will increment cycles and costs.
    Persistence: Metrics are saved to the DB to reflect historical machine wear and tear.
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

    # 2. Identify assigned machines for status and consumption updates
    machine_ids = [
        m_id for m_id in [booking_data.washer_id, booking_data.dryer_id]
        if m_id is not None
    ]

    # 3. Calculate consumption costs based on the specific Service Type
    # This uses the duration (minutes) defined in PredictionService
    consumption = PredictionService.calculate_booking_consumption(booking_data.service_type)

    # 4. Validate and update machine data in real-time
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
        
        if machine.status == "Busy":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is already in use."
            )

        # --- CUMULATIVE METRIC UPDATES ---
        # Update physical status
        machine.status = "Busy"
        machine.total_cycles += 1 
        
        # Add new consumption costs to the machine's historical running totals
        machine.total_electricity_cost += consumption["electricity"]
        machine.total_water_cost += consumption["water"]
        machine.total_detergent_cost += consumption["detergent"]
        
        # Set the timer based on the Service Type configuration
        service_config = PredictionService.SERVICE_CONFIG.get(
            booking_data.service_type, {"time": 45}
        )
        machine.remaining_time = service_config["time"]

    try:
        db.add(new_booking)
        db.commit()

        # RE-FETCH WITH JOINEDLOAD to provide a full UI update for the Service Terminal
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
    Fetches all non-Claimed bookings with full machine details for real-time monitoring.
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
    Handles the booking lifecycle and hardware release.
    Status transitions release machines back to 'Available' while preserving 
    the cumulative data for financial reporting.
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

    # RELEASE LOGIC: Return machines to available state upon completion or pickup.
    # We stop the timer but keep the total_cycles and total_costs intact.
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
                if machine.status != "Maintenance":
                    machine.status = "Available"
                    machine.remaining_time = 0 

    try:
        db.commit()

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