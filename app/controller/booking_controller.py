from sqlalchemy.orm import Session, joinedload
from app.models import Booking, Machine
from app.schemas import BookingCreate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status
from datetime import datetime, timezone


def create_booking(db: Session, booking_data: BookingCreate, shop_id: int):
    """
    Creates a new booking, sets machines to Busy, injects exact service
    duration into remaining_time, and recalculates profitability metrics.
    """
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
                detail=f"Machine ID {m_id} not found in this shop."
            )
        if machine.status == "Maintenance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is under maintenance."
            )
        if machine.status == "Busy":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} {machine.machine_number} is already occupied."
            )

        # ── Update real-time telemetry ────────────────────────────────────────
        machine.status = "Busy"
        machine.current_service_type = booking_data.service_type
        machine.current_price = booking_data.total_price
        machine.total_cycles += 1

        # Inject exact duration so frontend countdown is accurate
        machine.remaining_time = PredictionService.get_duration(
            booking_data.service_type, booking_data.loads
        )

        # ── Recalculate profitability ─────────────────────────────────────────
        overhead = PredictionService.get_overhead(machine.machine_type)
        net_profit = booking_data.total_price - overhead["total_overhead"]
        machine.net_profit_accumulated = (
            getattr(machine, "net_profit_accumulated", 0.0) or 0.0
        ) + net_profit
        machine.profitability_rate = max(
            0.0,
            ((booking_data.total_price - overhead["total_overhead"])
             / booking_data.total_price * 100)
            if booking_data.total_price > 0 else 0.0
        )

    try:
        db.add(new_booking)
        db.commit()

        # Re-fetch with joinedload to populate washer/dryer nested objects
        # (models.py has lazy="joined" but explicit reload ensures fresh data)
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
    Returns all non-Claimed bookings with nested machine objects
    so the Service Terminal displays W1/D3 labels correctly.
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
    Advances booking lifecycle and releases machines when done.
    Resets all real-time telemetry fields on the freed machines.
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

    if new_status in ["Ready", "Claimed"]:
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
            detail=f"Status Update Failed: {str(e)}"
        )
