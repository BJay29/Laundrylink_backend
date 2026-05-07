from sqlalchemy.orm import Session, joinedload
from app.models import Booking, Machine
from app.schemas import BookingCreate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status
from datetime import datetime, timezone

def create_booking(db: Session, booking_data: BookingCreate, shop_id: int):
    """
    Creates a new booking, sets machines to 'Busy', and updates telemetry.
    Calculates profitability and increments ACCUMULATED costs for utility tracking.
    
    Now captures 'booking_timestamp' for future peak-hour forecasting.
    """
    
    # NEW: Capture the timestamp from the request, or default to current UTC time
    # This is the key data point for your future AI Forecasting charts.
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
        # Syncing both timestamp fields for maximum data integrity
        booking_timestamp=actual_booking_time,
        created_at=datetime.now(timezone.utc)
    )

    # Gather assigned hardware IDs for telemetry update
    assigned_ids = [
        m_id for m_id in [booking_data.washer_id, booking_data.dryer_id]
        if m_id is not None
    ]

    for m_id in assigned_ids:
        machine = db.query(Machine).filter(
            Machine.id == m_id,
            Machine.shop_id == shop_id
        ).first()

        if not machine:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Hardware ID {m_id} not registered in current shop."
            )
        
        # Operational integrity guard clauses
        if machine.status == "Maintenance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is Offline for Maintenance."
            )
        if machine.status == "Busy":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is currently occupied."
            )

        # --- 1. UPDATE REAL-TIME TELEMETRY ---
        machine.status = "Busy"
        machine.current_service_type = booking_data.service_type
        machine.current_price = booking_data.total_price
        machine.total_cycles += 1

        # Triggers the React countdown timer based on service type
        machine.remaining_time = PredictionService.get_machine_runtime(
            machine.machine_type, booking_data.service_type
        )

        # --- 2. RESOURCE CONSUMPTION TRACKING ---
        overhead_data = PredictionService.get_overhead(machine.machine_type)
        
        machine.accumulated_electricity += overhead_data.get("electricity_cost", 0.0)
        machine.accumulated_water += overhead_data.get("water_cost", 0.0)
        machine.accumulated_detergent += overhead_data.get("detergent_cost", 0.0)

        # --- 3. DYNAMIC PROFITABILITY CALCULATION ---
        overhead_cost = overhead_data.get("total_overhead", 0.0)
        net_profit = booking_data.total_price - overhead_cost
        
        # Updates the field that matches your 'net_profit_accumulated' column fix
        machine.net_profit_accumulated += net_profit

        # Calculate Margin for Dashboard progress bars
        if booking_data.total_price > 0:
            margin = (net_profit / booking_data.total_price) * 100
            machine.profitability_rate = max(0.0, min(100.0, margin))
        else:
            machine.profitability_rate = 0.0

    try:
        db.add(new_booking)
        db.commit()

        # Re-fetch with joinedload to include machine labels (W1, D2) for the UI
        return (
            db.query(Booking)
            .options(
                joinedload(Booking.washer),
                joinedload(Booking.dryer)
            )
            .filter(Booking.id == new_booking.id)
            .first()
        )

    except Exception as e:
        db.rollback()
        print(f"CRITICAL TRANSACTION ERROR: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database Transactional Error: {str(e)}"
        )


def get_active_bookings(db: Session, shop_id: int):
    """
    Retrieves all non-finalized laundry tasks. 
    Optimized with joinedload to prevent N+1 performance issues.
    """
    return (
        db.query(Booking)
        .options(
            joinedload(Booking.washer),
            joinedload(Booking.dryer)
        )
        .filter(
            Booking.shop_id == shop_id,
            Booking.status.notin_(["Claimed", "Cancelled"])
        )
        .order_by(Booking.booking_timestamp.desc()) # Order by the actual booking time
        .all()
    )


def update_booking_status(db: Session, booking_id: int, new_status: str, shop_id: int):
    """
    Updates lifecycle status and releases hardware resources when finished.
    """
    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.shop_id == shop_id
    ).first()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction record not found."
        )

    booking.status = new_status

    # Release machines back to 'Available' if service is complete or cancelled
    if new_status in ["Ready", "Claimed", "Cancelled"]:
        assigned_ids = [
            m_id for m_id in [booking.washer_id, booking.dryer_id]
            if m_id is not None
        ]
        
        if assigned_ids:
            machines = db.query(Machine).filter(
                Machine.id.in_(assigned_ids),
                Machine.shop_id == shop_id
            ).all()
            
            for machine in machines:
                # Do not override manual Maintenance status
                if machine.status != "Maintenance":
                    machine.status = "Available"
                    machine.remaining_time = 0
                    machine.current_service_type = "None"
                    machine.current_price = 0.0

    try:
        db.commit()
        return (
            db.query(Booking)
            .options(
                joinedload(Booking.washer),
                joinedload(Booking.dryer)
            )
            .filter(Booking.id == booking_id)
            .first()
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Status Lifecycle Error: {str(e)}"
        )