from app.models import Booking, Machine, Setting, InventoryItem
from app.schemas import BookingCreate
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timezone

def create_booking(db: Session, booking_data: BookingCreate, shop_id: int):
    """
    Creates a new booking, updates machine status to 'Busy', and syncs telemetry.
    Automatically deducts detergent stock if 'add_detergent' is enabled.
    """
    
    # --- 1. FETCH LIVE PRICING SETTINGS ---
    settings = db.query(Setting).filter(Setting.shop_id == shop_id).first()
    if not settings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop settings not found. Please configure pricing in Settings."
        )

    # --- 2. AUTOMATED INVENTORY DEDUCTION ---
    # If the user selected 'add_detergent', we find the detergent item and reduce its stock
    if booking_data.add_detergent:
        detergent_item = db.query(InventoryItem).filter(
            InventoryItem.shop_id == shop_id,
            InventoryItem.item_name.ilike("%Detergent%")
        ).first()

        if detergent_item:
            if detergent_item.current_stock >= detergent_item.usage_rate:
                detergent_item.current_stock -= detergent_item.usage_rate
            else:
                # Optional: Raise error if out of stock, or proceed with warning
                pass

    # Ensure the timestamp is timezone-aware
    actual_booking_time = booking_data.booking_timestamp or datetime.now(timezone.utc)

    # Initialize the new booking record
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

    # Identify assigned machines for telemetry updates
    assigned_ids = [m_id for m_id in [booking_data.washer_id, booking_data.dryer_id] if m_id is not None]

    for m_id in assigned_ids:
        machine = db.query(Machine).filter(Machine.id == m_id, Machine.shop_id == shop_id).first()

        if not machine:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Hardware ID {m_id} is not registered in this shop."
            )
        
        # Guard clause for hardware availability
        if machine.status == "Maintenance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} #{machine.machine_number} is Offline for Maintenance."
            )
        
        # --- 3. UPDATE MACHINE REAL-TIME STATUS ---
        machine.status = "Busy"
        machine.current_service_type = booking_data.service_type
        machine.current_price = booking_data.total_price
        machine.total_cycles += 1

        # Calculate remaining runtime
        machine.remaining_time = PredictionService.get_machine_runtime(
            machine.machine_type, booking_data.service_type
        )

        # --- 4. DYNAMIC OVERHEAD & PROFIT TRACKING ---
        overhead_data = PredictionService.get_overhead(machine.machine_type)
        
        machine.accumulated_electricity += overhead_data.get("electricity_cost", 0.0)
        machine.accumulated_water += overhead_data.get("water_cost", 0.0)
        machine.accumulated_detergent += overhead_data.get("detergent_cost", 0.0)

        # Calculate net profit
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
    Retrieves all non-finalized tasks for the Terminal UI. 
    Pre-loads Machine data to prevent 'WAITING' or 'NULL' labels.
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
    Manages the booking lifecycle and releases machine resources back to 'Available'.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id, Booking.shop_id == shop_id).first()

    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction record not found.")

    booking.status = new_status

    # Reset hardware state if the task is finished or cancelled
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