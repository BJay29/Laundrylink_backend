from app.models import Booking, Machine, Setting, InventoryItem, InventoryLog
from app.schemas import BookingCreate, BookingAssignMachine
from app.services.prediction_service import PredictionService
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timezone


def create_booking(db: Session, booking_data: BookingCreate, shop_id: int):
    """
    Creates a new booking.
    UPDATED LOGIC:
    - If washer_id and dryer_id are both None → status = "Pending"
      (no machine assigned yet, operator will assign later from the terminal)
    - If at least one machine is assigned → status = "In Progress"
      (machines are marked Busy and telemetry is updated as before)
    """

    # --- 1. FETCH LIVE PRICING SETTINGS ---
    settings = db.query(Setting).filter(Setting.shop_id == shop_id).first()
    if not settings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop settings not found. Please configure pricing in Settings."
        )

    actual_booking_time = booking_data.booking_timestamp or datetime.now(timezone.utc)

    # --- 2. HANDLE INVENTORY ---
    inventory_item_id = None
    if booking_data.inventory_item_id is not None:
        inventory_item = db.query(InventoryItem).filter(
            InventoryItem.id == booking_data.inventory_item_id,
            InventoryItem.shop_id == shop_id
        ).first()

        if not inventory_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Selected inventory item not found for this shop."
            )

        quantity_to_use = booking_data.inventory_quantity_used
        if quantity_to_use is None or quantity_to_use <= 0:
            quantity_to_use = max(booking_data.loads * (inventory_item.usage_rate or 1.0), 0.01)

        if inventory_item.current_stock < quantity_to_use:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Inventory item has insufficient stock for the booking."
            )

        inventory_item.current_stock -= quantity_to_use
        usage_log = InventoryLog(item_id=inventory_item.id, quantity_used=quantity_to_use)
        db.add(usage_log)
        inventory_item_id = inventory_item.id

    # --- 3. DETERMINE INITIAL STATUS ---
    # If no machine is assigned at booking time, set status to Pending.
    # The operator will assign a machine later via the terminal.
    assigned_ids = [
        m_id for m_id in [booking_data.washer_id, booking_data.dryer_id]
        if m_id is not None
    ]
    initial_status = "In Progress" if assigned_ids else "Pending"

    # --- 4. CREATE THE BOOKING RECORD ---
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
        status=initial_status,
        washer_id=booking_data.washer_id,
        dryer_id=booking_data.dryer_id,
        inventory_item_id=inventory_item_id,
        shop_id=shop_id,
        booking_timestamp=actual_booking_time,
        created_at=datetime.now(timezone.utc)
    )

    # --- 5. UPDATE MACHINE TELEMETRY (only if machines are assigned) ---
    for m_id in assigned_ids:
        machine = db.query(Machine).filter(
            Machine.id == m_id,
            Machine.shop_id == shop_id
        ).first()

        if not machine:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Hardware ID {m_id} is not registered in this shop."
            )

        if machine.status == "Maintenance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} #{machine.machine_number} is Offline for Maintenance."
            )

        machine.status = "Busy"
        machine.current_service_type = booking_data.service_type
        machine.current_price = booking_data.total_price
        machine.total_cycles += 1

        machine.remaining_time = PredictionService.get_machine_runtime(
            machine.machine_type, booking_data.service_type
        )

        overhead_data = PredictionService.get_overhead(machine.machine_type)
        machine.accumulated_electricity += overhead_data.get("electricity_cost", 0.0)
        machine.accumulated_water += overhead_data.get("water_cost", 0.0)
        machine.accumulated_detergent += overhead_data.get("detergent_cost", 0.0)

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
        db.refresh(new_booking)

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


def assign_machine_to_booking(db: Session, booking_id: int, assign_data: "BookingAssignMachine", shop_id: int):
    """
    NEW FUNCTION
    Assigns a washer and/or dryer to an existing Pending booking that has no machine.
    - Validates both machines belong to this shop and are available.
    - Marks machines as Busy and updates telemetry.
    - Transitions booking status from Pending → In Progress.
    """
    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.shop_id == shop_id
    ).first()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found."
        )

    if booking.status != "Pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot assign machine to a booking with status '{booking.status}'. Only Pending bookings can be assigned."
        )

    assigned_ids = [
        m_id for m_id in [assign_data.washer_id, assign_data.dryer_id]
        if m_id is not None
    ]

    if not assigned_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one machine (washer or dryer) must be provided."
        )

    for m_id in assigned_ids:
        machine = db.query(Machine).filter(
            Machine.id == m_id,
            Machine.shop_id == shop_id
        ).first()

        if not machine:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Hardware ID {m_id} is not registered in this shop."
            )

        if machine.status == "Maintenance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} #{machine.machine_number} is currently under Maintenance."
            )

        busy_statuses = ["busy", "in use", "running"]
        if machine.status.lower() in busy_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} #{machine.machine_number} is currently busy."
            )

        # Update machine telemetry
        machine.status = "Busy"
        machine.current_service_type = booking.service_type
        machine.current_price = booking.total_price
        machine.total_cycles += 1

        machine.remaining_time = PredictionService.get_machine_runtime(
            machine.machine_type, booking.service_type
        )

        overhead_data = PredictionService.get_overhead(machine.machine_type)
        machine.accumulated_electricity += overhead_data.get("electricity_cost", 0.0)
        machine.accumulated_water += overhead_data.get("water_cost", 0.0)
        machine.accumulated_detergent += overhead_data.get("detergent_cost", 0.0)

        overhead_total = overhead_data.get("total_overhead", 0.0)
        net_profit = booking.total_price - overhead_total
        machine.net_profit_accumulated += net_profit

        if booking.total_price > 0:
            margin = (net_profit / booking.total_price) * 100
            machine.profitability_rate = max(0.0, min(100.0, margin))
        else:
            machine.profitability_rate = 0.0

    # Assign machines to the booking
    if assign_data.washer_id is not None:
        booking.washer_id = assign_data.washer_id
    if assign_data.dryer_id is not None:
        booking.dryer_id = assign_data.dryer_id

    # Transition booking to In Progress
    booking.status = "In Progress"

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
            detail=f"Machine Assignment Error: {str(e)}"
        )


def get_active_bookings(db: Session, shop_id: int):
    """
    Retrieves all non-finalized tasks for the Terminal UI.
    Includes Pending bookings (no machine) and In Progress bookings.
    Pre-loads Machine data to prevent null labels.
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

    # Release machines when the task is finished or cancelled
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
