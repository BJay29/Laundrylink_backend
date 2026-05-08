from app.models import Booking, Machine
from app.schemas import BookingCreate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timezone

def create_booking(db: Session, booking_data: BookingCreate, shop_id: int):
    """
    Creates a new booking, sets machines to 'Busy', and updates telemetry.
    Calculates profitability and increments accumulated costs for utility tracking.
    """
    
    # Ensure the timestamp is timezone-aware for the forecasting engine
    actual_booking_time = booking_data.booking_timestamp or datetime.now(timezone.utc)

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
        booking_timestamp=actual_booking_time,
        created_at=datetime.now(timezone.utc)
    )

    # Identify assigned hardware IDs for telemetry and resource updates
    assigned_ids = [m_id for m_id in [booking_data.washer_id, booking_data.dryer_id] if m_id is not None]

    for m_id in assigned_ids:
        machine = db.query(Machine).filter(Machine.id == m_id, Machine.shop_id == shop_id).first()

        if not machine:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Hardware ID {m_id} is not registered in this shop."
            )
        
        # Operational integrity guards to prevent overbooking
        if machine.status == "Maintenance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} #{machine.machine_number} is Offline for Maintenance."
            )
        if machine.status == "Busy":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} #{machine.machine_number} is currently occupied."
            )

        # --- 1. UPDATE REAL-TIME TELEMETRY ---
        machine.status = "Busy"
        machine.current_service_type = booking_data.service_type
        machine.current_price = booking_data.total_price
        machine.total_cycles += 1

        # Set machine runtime for frontend countdowns
        machine.remaining_time = PredictionService.get_machine_runtime(
            machine.machine_type, booking_data.service_type
        )

        # --- 2. RESOURCE CONSUMPTION TRACKING ---
        overhead_data = PredictionService.get_overhead(machine.machine_type)
        machine.accumulated_electricity += overhead_data.get("electricity_cost", 0.0)
        machine.accumulated_water += overhead_data.get("water_cost", 0.0)
        machine.accumulated_detergent += overhead_data.get("detergent_cost", 0.0)

        # --- 3. DYNAMIC PROFITABILITY CALCULATION ---
        overhead_total = overhead_data.get("total_overhead", 0.0)
        net_profit = booking_data.total_price - overhead_total
        machine.net_profit_accumulated += net_profit

        if booking_data.total_price > 0:
            margin = (net_profit / booking_data.total_price) * 100
            machine.profitability_rate = max(0.0, min(100.0, margin))
        else:
            machine.profitability_rate = 0.0

    try:
        db.add(new_booking)
        db.commit()

        # FIXED: Re-fetch with joinedload ensures the frontend receives washer/dryer labels immediately
        return (
            db.query(Booking)
            .options(joinedload(Booking.washer), joinedload(Booking.dryer))
            .filter(Booking.id == new_booking.id)
            .first()
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database Transactional Error: {str(e)}"
        )


def get_active_bookings(db: Session, shop_id: int):
    """
    Retrieves all non-finalized laundry tasks for the Service Terminal. 
    Uses joinedload to prevent 'WAITING' labels in the UI.
    """
    return (
        db.query(Booking)
        .options(joinedload(Booking.washer), joinedload(Booking.dryer))
        .filter(
            Booking.shop_id == shop_id,
            Booking.status.notin_(["Claimed", "Cancelled"])
        )
        .order_by(Booking.booking_timestamp.desc()) 
        .all()
    )


def update_booking_status(db: Session, booking_id: int, new_status: str, shop_id: int):
    """
    Manages the lifecycle of a booking and releases hardware resources upon completion.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id, Booking.shop_id == shop_id).first()

    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction record not found.")

    booking.status = new_status

    # Reset hardware state if the service is finished
    if new_status in ["Ready", "Claimed", "Cancelled"]:
        assigned_ids = [m_id for m_id in [booking.washer_id, booking.dryer_id] if m_id is not None]
        
        if assigned_ids:
            machines = db.query(Machine).filter(
                Machine.id.in_(assigned_ids),
                Machine.shop_id == shop_id
            ).all()
            
            for machine in machines:
                if machine.status != "Maintenance":
                    machine.status = "Available"
                    machine.remaining_time = 0
                    machine.current_service_type = "None"
                    machine.current_price = 0.0

    try:
        db.commit()
        # FIXED: Returns joined data so Terminal UI updates correctly after status change
        return (
            db.query(Booking)
            .options(joinedload(Booking.washer), joinedload(Booking.dryer))
            .filter(Booking.id == booking_id)
            .first()
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Status Lifecycle Error: {str(e)}"
        )