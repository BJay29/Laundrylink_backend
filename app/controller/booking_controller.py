from sqlalchemy.orm import Session, joinedload
from app.models import Booking, Machine
from app.schemas import BookingCreate
from fastapi import HTTPException, status
from datetime import datetime, timezone

def create_booking(db: Session, booking_data: BookingCreate, shop_id: int):
    """
    Creates a new laundry transaction and links it to specific hardware units.
    Updates real-time machine status, service type, and financial profitability metrics.
    """

    # 1. Initialize new booking object
    # Fixed: Ensure shop_id is explicitly assigned from the session/auth context
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
        status="In Progress", # Bookings start active upon finalization
        washer_id=booking_data.washer_id,
        dryer_id=booking_data.dryer_id,
        shop_id=shop_id,
        created_at=datetime.now(timezone.utc)
    )

    # 2. Collect assigned machine IDs
    # IMPORTANT: These must be the Primary Keys (ID), not the Machine Number
    machine_ids = [
        m_id for m_id in [booking_data.washer_id, booking_data.dryer_id]
        if m_id is not None
    ]

    # 3. Validate machines and update real-time telemetry data
    for m_id in machine_ids:
        # We filter by both ID and shop_id to prevent cross-shop data leaks
        machine = db.query(Machine).filter(
            Machine.id == m_id,
            Machine.shop_id == shop_id
        ).first()

        # If this triggers, the ID sent from the frontend does not exist for this shop
        if not machine:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"System Sync: Machine ID {m_id} is not initialized in the database for this shop."
            )
        
        if machine.status == "Maintenance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is under maintenance."
            )
        
        if machine.status == "Busy":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is already processing another order."
            )

        # --- REAL-TIME TELEMETRY UPDATE ---
        # Update hardware state to reflect on the Machine Hub / Dashboard
        machine.status = "Busy"
        machine.current_service_type = booking_data.service_type
        machine.current_price = booking_data.total_price
        machine.total_cycles += 1 
        
        # --- PROFITABILITY CALCULATION ---
        # Standard utility rates (Can be moved to a settings table later)
        electricity_rate = 12.0  # PHP per kWh
        water_rate = 0.05        # PHP per Liter
        detergent_rate = 0.10    # PHP per ml

        # Calculate operational overhead based on machine-specific consumption averages
        overhead = (
            (machine.avg_electricity * electricity_rate) +
            (machine.avg_water * water_rate) +
            (machine.avg_detergent * detergent_rate)
        )
        
        # Track net profit per machine for business analytics
        net_profit = booking_data.total_price - overhead
        machine.net_profit_accumulated += net_profit

        # Calculate timer (approx 45 mins base + 5 mins per extra load)
        estimated_time = 45 + (max(0, booking_data.loads - 1) * 5)
        machine.remaining_time = estimated_time

    try:
        db.add(new_booking)
        db.commit()

        # Re-fetch with joined relations to ensure frontend gets full machine objects
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
            detail=f"Database Transaction Failed: {str(e)}"
        )


def get_active_bookings(db: Session, shop_id: int):
    """
    Retrieves all ongoing bookings with full hardware details for live monitoring.
    Excludes 'Claimed' orders to keep the Terminal view clean.
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
    Manages the lifecycle of a booking. 
    Resets real-time machine telemetry when a service is completed (Ready/Claimed).
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

    # RELEASE LOGIC: Unlock machines when the laundry is done or picked up
    if new_status in ["Ready", "Claimed"]:
        assigned_ids = [
            m_id for m_id in [booking.washer_id, booking.dryer_id]
            if m_id is not None
        ]

        if assigned_ids:
            # Update all linked machines in one query
            related_machines = db.query(Machine).filter(
                Machine.id.in_(assigned_ids),
                Machine.shop_id == shop_id
            ).all()

            for machine in related_machines:
                # Do not set to Available if the machine was put in Maintenance manually
                if machine.status != "Maintenance":
                    machine.status = "Available"
                    machine.remaining_time = 0 
                    machine.current_service_type = "None"
                    machine.current_price = 0.0

    try:
        db.commit()

        # Return updated booking with machine details for UI refresh
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
            detail=f"Status Update Failed: {str(e)}"
        )