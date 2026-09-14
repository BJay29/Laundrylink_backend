from app.models import Booking, Machine, Setting, ServiceType, BookingInventoryUsage, AddOn, PromoCode, BookingAddOnUsage, BookingMachineAssignment
from app.schemas import (
    BookingCreate, BookingAssignMachine, CustomerBookingCreate, PaymentStatusUpdate,
    MachineAssignmentInput, MoveLoadToDryerInput
)
from app.services.prediction_service import PredictionService
from app.services.ws_manager import manager
from app.controller import inventory_controller
from app.controller import notification_controller
from app.controller.activity_controller import log_activity
from app import models
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timezone


def create_booking(db: Session, booking_data: BookingCreate, current_user: models.User):
    """
    Creates a new booking.
    - If washer_id and dryer_id are both None → status = "Pending"
    - If at least one machine is assigned → status = "In Progress"

    NOTE (multi-machine assignment feature): ang washer_id/dryer_id sa
    BookingCreate ay LEGACY na ngayon — sinusuportahan pa rin dito para
    hindi masira ang existing single-machine flow (hal. 1-load bookings
    na direktang inaasignan ng machine sa mismong paggawa ng booking).
    Para sa multi-load bookings (loads > 1), iniiwan MUNANG "Pending"
    ang booking na ito (walang washer_id/dryer_id na ipapasa), tapos
    tatawagin ang BAGONG assign_machines_to_booking() sa ibaba bilang
    hiwalay na hakbang — doon nangyayari ang totoong N-machines-per-load
    na assignment gamit ang BookingMachineAssignment.

    UPDATED: machine.remaining_time now comes from the shop's own
    configured ServiceType.duration_minutes instead of
    PredictionService.get_machine_runtime()'s hardcoded estimate — the
    Machine Monitoring card reflects what the shop owner actually set
    in Optimization Settings.

    UPDATED: PredictionService.get_overhead() now takes (db, shop_id, ...)
    so machine cost telemetry (electricity/water/supplies) is computed
    using THIS shop's own configured rates from Optimization Settings,
    instead of hardcoded Naga City constants that ignored the Setting
    table entirely (previously, changing rates in the UI had zero effect
    on cost calculations here).

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id, so the action can be attributed to whoever actually
    performed it (current_user.full_name or current_user.email /
    current_user.role) instead of just knowing which shop it happened in.

    UPDATED (Payment): ini-set na rin ang payment_method galing sa
    booking_data (default "cash", tumutugma sa Walk-in terminal flow).
    payment_status ay laging nagsisimula sa "unpaid" (default sa model)
    — ang pag-mark bilang "Paid" ay hiwalay at manual na action ng staff
    (see mark_booking_as_paid() sa ibaba).

    NOTE: no is_online gate here — this is a staff-created booking from
    the Service Terminal itself, i.e. the terminal is, by definition,
    open and connected while this runs. The is_online safety net only
    applies to create_customer_booking() below (mobile app self-booking),
    where the customer's device has no way to know the terminal's live
    connection state on its own.
    """
    shop_id = current_user.shop_id

    # --- 1. FETCH OPERATIONAL SETTINGS (utility rates, minimum weight) ---
    settings = db.query(Setting).filter(Setting.shop_id == shop_id).first()
    if not settings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop settings not found. Please configure Optimization Settings first."
        )

    minimum_weight = settings.minimum_weight_kg or 6.0
    if booking_data.weight < minimum_weight:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Minimum booking weight is {minimum_weight}kg. Please adjust the weight."
        )

    # --- 2. VALIDATE SERVICE TYPE AGAINST THE SHOP'S OWN CATALOG ---
    service_type_record = (
        db.query(ServiceType)
        .filter(
            ServiceType.shop_id == shop_id,
            ServiceType.name == booking_data.service_type,
            ServiceType.is_active == True
        )
        .first()
    )
    if not service_type_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Service type '{booking_data.service_type}' is not configured for this shop. "
                "Please add it in Optimization Settings before creating a booking."
            )
        )

    actual_booking_time = booking_data.booking_timestamp or datetime.now(timezone.utc)

    # --- 3. VALIDATE + DEDUCT INVENTORY (MULTI-ITEM, ATOMIC) ---
    deducted_items = []
    for item_usage in booking_data.inventory_items:
        item = inventory_controller.validate_and_deduct_stock(
            db=db,
            item_id=item_usage.inventory_item_id,
            quantity=item_usage.quantity_used,
            shop_id=shop_id
        )
        deducted_items.append((item, item_usage.quantity_used))

    # --- 4. DETERMINE INITIAL STATUS (legacy single-machine path) ---
    assigned_ids = [
        m_id for m_id in [booking_data.washer_id, booking_data.dryer_id]
        if m_id is not None
    ]
    initial_status = "In Progress" if assigned_ids else "Pending"

    # --- 5. CREATE THE BOOKING RECORD ---
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
        shop_id=shop_id,
        source="terminal",
        payment_method=booking_data.payment_method or "cash",
        booking_timestamp=actual_booking_time,
        created_at=datetime.now(timezone.utc)
    )

    # --- 6. UPDATE MACHINE TELEMETRY (legacy path — only if machines are
    #    assigned inline at creation, i.e. single-load bookings). Multi-
    #    load bookings should NOT pass washer_id/dryer_id here — they
    #    stay "Pending" and use assign_machines_to_booking() instead. ---
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
        machine.remaining_time = service_type_record.duration_minutes

        overhead_data = PredictionService.get_overhead(db, shop_id, machine.machine_type)
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
        db.flush()

        for item, quantity_used in deducted_items:
            db.add(BookingInventoryUsage(
                booking_id=new_booking.id,
                inventory_item_id=item.id,
                quantity_used=quantity_used
            ))

        machine_note = ""
        if assigned_ids:
            machine_note = f" (machine assigned, {len(assigned_ids)} unit/s)"
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=(
                f"Created a booking for {booking_data.customer_name} "
                f"- {booking_data.service_type}, ₱{booking_data.total_price}{machine_note}"
            )
        )

        db.commit()
        db.refresh(new_booking)

        return (
            db.query(Booking)
            .options(
                joinedload(Booking.washer),
                joinedload(Booking.dryer),
                joinedload(Booking.inventory_usages),
                joinedload(Booking.add_ons_used),
                joinedload(Booking.machine_assignments),
            )
            .filter(Booking.id == new_booking.id)
            .first()
        )

    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database Transactional Error: {str(e)}"
        )


def assign_machine_to_booking(db: Session, booking_id: int, assign_data: "BookingAssignMachine", current_user: models.User):
    """
    LEGACY (multi-machine assignment feature) — single washer + single
    dryer lang, isang beses lang. Iniwan ito nang buo, hindi tinanggal,
    para sa backward compatibility habang tinatapos ang paglipat ng buong
    frontend papunta sa bagong assign_machines_to_booking() /
    move_load_to_dryer() sa ibaba. Para sa BAGONG bookings, gamitin na
    ang bagong dalawang function na iyon sa halip nito.
    """
    shop_id = current_user.shop_id

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

    service_type_record = (
        db.query(ServiceType)
        .filter(
            ServiceType.shop_id == shop_id,
            ServiceType.name == booking.service_type
        )
        .first()
    )
    duration_minutes = (
        service_type_record.duration_minutes
        if service_type_record
        else None
    )

    assigned_machine_labels = []

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

        machine.status = "Busy"
        machine.current_service_type = booking.service_type
        machine.current_price = booking.total_price
        machine.total_cycles += 1

        machine.remaining_time = (
            duration_minutes
            if duration_minutes is not None
            else PredictionService.get_machine_runtime(machine.machine_type, booking.service_type)
        )

        overhead_data = PredictionService.get_overhead(db, shop_id, machine.machine_type)
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

        assigned_machine_labels.append(f"{machine.machine_type} #{machine.machine_number}")

    if assign_data.washer_id is not None:
        booking.washer_id = assign_data.washer_id
    if assign_data.dryer_id is not None:
        booking.dryer_id = assign_data.dryer_id

    booking.status = "In Progress"

    try:
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=(
                f"Assigned machine(s) to {booking.customer_name}'s booking "
                f"({', '.join(assigned_machine_labels)})"
            )
        )

        db.commit()
        return (
            db.query(Booking)
            .options(
                joinedload(Booking.washer),
                joinedload(Booking.dryer),
                joinedload(Booking.inventory_usages),
                joinedload(Booking.add_ons_used),
                joinedload(Booking.machine_assignments),
            )
            .filter(Booking.id == booking_id)
            .first()
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Machine Assignment Error: {str(e)}"
        )


# =========================================================
# MULTI-MACHINE ASSIGNMENT FUNCTIONS (NEW)
# =========================================================

def _bind_machine_telemetry(db: Session, shop_id: int, machine: Machine, service_type_name: str, total_price: float, duration_minutes: int):
    """
    NEW — Shared helper factored out of the per-machine telemetry block
    that used to be duplicated inline in assign_machine_to_booking() and
    create_booking(). Marks the machine Busy, sets its countdown, and
    applies overhead/profitability telemetry using the shop's own
    configured rates. Used by BOTH assign_machines_to_booking() (washer
    phase) and move_load_to_dryer() (dryer phase) below, so both phases
    of a load get the same telemetry treatment as the legacy single-
    machine flow did.
    """
    machine.status = "Busy"
    machine.current_service_type = service_type_name
    machine.current_price = total_price
    machine.total_cycles += 1
    machine.remaining_time = duration_minutes

    overhead_data = PredictionService.get_overhead(db, shop_id, machine.machine_type)
    machine.accumulated_electricity += overhead_data.get("electricity_cost", 0.0)
    machine.accumulated_water += overhead_data.get("water_cost", 0.0)
    machine.accumulated_detergent += overhead_data.get("detergent_cost", 0.0)

    overhead_total = overhead_data.get("total_overhead", 0.0)
    net_profit = total_price - overhead_total
    machine.net_profit_accumulated += net_profit

    if total_price > 0:
        margin = (net_profit / total_price) * 100
        machine.profitability_rate = max(0.0, min(100.0, margin))
    else:
        machine.profitability_rate = 0.0


def _release_machine(machine: Machine):
    """
    NEW — Shared helper for freeing up a machine back to "Available",
    same pattern as the release block inside update_booking_status().
    Skips machines currently in Maintenance (those stay in Maintenance
    regardless of booking lifecycle).
    """
    if machine.status != "Maintenance":
        machine.status = "Available"
        machine.remaining_time = 0
        machine.current_service_type = "None"
        machine.current_price = 0.0


def assign_machines_to_booking(db: Session, booking_id: int, assign_data: MachineAssignmentInput, current_user: models.User):
    """
    NEW — Multi-machine assignment para sa isang Pending booking.
    Kailangan eksaktong kasing-dami ng booking.loads ang machine_ids na
    ipinasa (isang machine per load).

    Ang TYPE ng machine na hinihingi (Washer o Dryer) ay base sa
    service_type_record.required_phases:
      - "full_service" o "wash_only" → WASHERS ang kailangan; bawat
        load ay nagsisimula sa phase="washing". Para sa "full_service",
        may susunod pang "Move to Dryer" step (move_load_to_dryer()).
        Para sa "wash_only", wala nang susunod na phase — deretso na
        sa "Ready" ang buong booking sa pamamagitan ng normal na status
        update kapag tapos na ang washing.
      - "dry_only" → DRYERS agad ang kailangan; bawat load ay direktang
        nagsisimula sa phase="drying" (walang washing phase na dinadaanan).

    Gumagawa ng isang BookingMachineAssignment row PER LOAD (load_number
    1-indexed), tapos ise-set ang Booking.status papuntang "In Progress".

    Kung walang ServiceType record na nakita (hal. na-delete na pagkatapos
    gawin ang booking), fina-fallback sa "full_service" (washers) bilang
    default, at PredictionService.get_machine_runtime() bilang fallback
    duration — parehong fallback pattern gaya ng legacy
    assign_machine_to_booking() sa itaas.
    """
    shop_id = current_user.shop_id

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
            detail=f"Cannot assign machines to a booking with status '{booking.status}'. Only Pending bookings can be assigned."
        )

    existing_assignments = (
        db.query(BookingMachineAssignment)
        .filter(BookingMachineAssignment.booking_id == booking.id)
        .count()
    )
    if existing_assignments > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This booking already has machine assignments. Use Move to Dryer for per-load transitions instead."
        )

    required_loads = booking.loads or 1
    if len(assign_data.machine_ids) != required_loads:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This booking has {required_loads} load(s) — please select exactly {required_loads} machine(s)."
        )

    service_type_record = (
        db.query(ServiceType)
        .filter(
            ServiceType.shop_id == shop_id,
            ServiceType.name == booking.service_type
        )
        .first()
    )
    required_phases = service_type_record.required_phases if service_type_record else "full_service"
    duration_minutes = (
        service_type_record.duration_minutes
        if service_type_record
        else PredictionService.get_machine_runtime("Washer", booking.service_type)
    )

    target_type = "Dryer" if required_phases == "dry_only" else "Washer"
    initial_phase = "drying" if required_phases == "dry_only" else "washing"
    now = datetime.now(timezone.utc)

    new_assignments = []
    assigned_machine_labels = []

    for load_number, m_id in enumerate(assign_data.machine_ids, start=1):
        machine = db.query(Machine).filter(
            Machine.id == m_id,
            Machine.shop_id == shop_id
        ).first()

        if not machine:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Hardware ID {m_id} is not registered in this shop."
            )

        if machine.machine_type != target_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"{machine.machine_type} #{machine.machine_number} cannot be used here — "
                    f"this service requires {target_type.lower()}s for the first phase."
                )
            )

        if machine.status == "Maintenance":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} #{machine.machine_number} is Offline for Maintenance."
            )

        busy_statuses = ["busy", "in use", "running"]
        if machine.status.lower() in busy_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{machine.machine_type} #{machine.machine_number} is currently busy."
            )

        _bind_machine_telemetry(db, shop_id, machine, booking.service_type, booking.total_price, duration_minutes)

        assignment = BookingMachineAssignment(
            booking_id=booking.id,
            load_number=load_number,
            phase=initial_phase,
            washer_id=m_id if target_type == "Washer" else None,
            dryer_id=m_id if target_type == "Dryer" else None,
            washing_started_at=now if target_type == "Washer" else None,
            drying_started_at=now if target_type == "Dryer" else None,
        )
        new_assignments.append(assignment)
        assigned_machine_labels.append(f"Load {load_number}: {machine.machine_type} #{machine.machine_number}")

    booking.status = "In Progress"

    try:
        for assignment in new_assignments:
            db.add(assignment)

        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=(
                f"Assigned {len(new_assignments)} machine(s) to {booking.customer_name}'s booking "
                f"({'; '.join(assigned_machine_labels)})"
            )
        )

        db.commit()
        return (
            db.query(Booking)
            .options(
                joinedload(Booking.washer),
                joinedload(Booking.dryer),
                joinedload(Booking.inventory_usages),
                joinedload(Booking.add_ons_used),
                joinedload(Booking.machine_assignments),
            )
            .filter(Booking.id == booking_id)
            .first()
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Machine Assignment Error: {str(e)}"
        )


def move_load_to_dryer(db: Session, booking_id: int, load_number: int, move_data: MoveLoadToDryerInput, current_user: models.User):
    """
    NEW — "Move to Dryer" action para sa isang SPECIFIC LOAD lang (hindi
    buong booking). Real-time na pinipili ang available dryer sa mismong
    sandaling ito tinawag — hindi paunang commitment nang ginawa pa lang
    ang unang assignment (see BookingMachineAssignment docstring sa
    models.py para sa buong reasoning kung bakit ganito ang disenyo).

    Ire-release ang washer ng load na ito (papunta sa "Available"), tapos
    bibigyan ito ng napiling dryer, ise-set ang phase papuntang "drying",
    at magsisimula ang bagong countdown gamit ang PAREHONG
    duration_minutes ng service (walang hiwalay na configured duration
    para sa dry phase — parehong setting ang ginagamit sa dalawang phase).

    Hindi ito applicable sa mga load na "dry_only" ang required_phases
    (nagsisimula na sila agad sa "drying" mula sa assign_machines_to_
    booking(), walang "washing" phase na dadaanan).
    """
    shop_id = current_user.shop_id

    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.shop_id == shop_id
    ).first()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found."
        )

    assignment = (
        db.query(BookingMachineAssignment)
        .filter(
            BookingMachineAssignment.booking_id == booking.id,
            BookingMachineAssignment.load_number == load_number
        )
        .first()
    )
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Load {load_number} not found for this booking."
        )

    if assignment.phase != "washing":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Load {load_number} is not currently in the washing phase (current phase: '{assignment.phase}')."
        )

    dryer = db.query(Machine).filter(
        Machine.id == move_data.dryer_id,
        Machine.shop_id == shop_id
    ).first()

    if not dryer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Hardware ID {move_data.dryer_id} is not registered in this shop."
        )

    if dryer.machine_type != "Dryer":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{dryer.machine_type} #{dryer.machine_number} is not a dryer."
        )

    if dryer.status == "Maintenance":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dryer #{dryer.machine_number} is Offline for Maintenance."
        )

    busy_statuses = ["busy", "in use", "running"]
    if dryer.status.lower() in busy_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dryer #{dryer.machine_number} is currently busy."
        )

    service_type_record = (
        db.query(ServiceType)
        .filter(
            ServiceType.shop_id == shop_id,
            ServiceType.name == booking.service_type
        )
        .first()
    )
    duration_minutes = (
        service_type_record.duration_minutes
        if service_type_record
        else PredictionService.get_machine_runtime("Dryer", booking.service_type)
    )

    # Release the washer this load was using.
    if assignment.washer_id:
        washer = db.query(Machine).filter(
            Machine.id == assignment.washer_id,
            Machine.shop_id == shop_id
        ).first()
        if washer:
            _release_machine(washer)

    now = datetime.now(timezone.utc)
    assignment.washing_completed_at = now
    assignment.dryer_id = dryer.id
    assignment.phase = "drying"
    assignment.drying_started_at = now

    _bind_machine_telemetry(db, shop_id, dryer, booking.service_type, booking.total_price, duration_minutes)

    try:
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=(
                f"Moved Load {load_number} of {booking.customer_name}'s booking "
                f"to Dryer #{dryer.machine_number}"
            )
        )

        db.commit()
        return (
            db.query(Booking)
            .options(
                joinedload(Booking.washer),
                joinedload(Booking.dryer),
                joinedload(Booking.inventory_usages),
                joinedload(Booking.add_ons_used),
                joinedload(Booking.machine_assignments),
            )
            .filter(Booking.id == booking_id)
            .first()
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Move to Dryer Error: {str(e)}"
        )


def get_active_bookings(db: Session, shop_id: int):
    """
    Retrieves all non-finalized tasks for the Terminal UI.

    UPDATED: also excludes "Awaiting Approval" and "Declined" — these
    are shown only in the separate approval panel (get_awaiting_approval_
    bookings below), not mixed into the normal Service Terminal list.
    An "Awaiting Approval" booking only appears here once it has been
    Accepted (status becomes "Pending", same as any manual booking).

    NOTE: hindi ito ginagalaw ng Activity Log — read-only na operation
    ito (walang binabago), kaya walang kailangang i-log dito. Pinanatili
    ang shop_id-only signature (hindi current_user) dahil hindi ito
    kailangan ng actor attribution.
    """
    return (
        db.query(Booking)
        .options(
            joinedload(Booking.washer),
            joinedload(Booking.dryer),
            joinedload(Booking.inventory_usages),
            joinedload(Booking.add_ons_used),
            joinedload(Booking.machine_assignments),
        )
        .filter(
            Booking.shop_id == shop_id,
            Booking.status.notin_(["Claimed", "Cancelled", "Awaiting Approval", "Declined"])
        )
        .order_by(Booking.booking_timestamp.desc())
        .all()
    )


def _get_status_notification_content(new_status: str, booking: Booking):
    """
    NEW — Nagbabalik ng (type, title, message) tuple na naka-tugma sa
    PARTIKULAR na status na pinasok ng booking. Ito ang gumagawa ng
    magkakaibang notification kada pagbabago (In Progress, Ready,
    Claimed, Cancelled) sa halip na iisang generic na "may update sa
    booking mo" na paulit-ulit lang.

    Nagbabalik ng None kung walang dapat i-notify para sa status na ito
    (hal. "Pending", na karaniwang internal transition lang, hindi
    kailangang batid agad ng customer bawat oras).
    """
    shop_label = booking.shop_name or "the shop"

    content_map = {
        "In Progress": (
            "status_in_progress",
            "Booking In Progress",
            f"Your {booking.service_type} booking at {shop_label} is now in progress."
        ),
        "Ready": (
            "status_ready",
            "Ready for Pickup",
            f"Your laundry at {shop_label} is ready for pickup!"
        ),
        "Claimed": (
            "status_claimed",
            "Booking Completed",
            f"Your {booking.service_type} booking at {shop_label} has been completed. Thank you for booking with us!"
        ),
        "Cancelled": (
            "status_cancelled",
            "Booking Cancelled",
            f"Your {booking.service_type} booking at {shop_label} was cancelled by the shop."
        ),
    }
    return content_map.get(new_status)


def update_booking_status(db: Session, booking_id: int, new_status: str, current_user: models.User):
    """
    Manages the booking lifecycle and releases machine resources back to 'Available'.

    UPDATED (multi-machine assignment feature): ang pag-release ng
    machines papuntang "Available" ay hindi na umaasa lamang sa legacy
    washer_id/dryer_id — ngayon ay ini-iterate na rin ang lahat ng
    Booking.machine_assignments (kung meron), at ire-release ang bawat
    washer_id/dryer_id na naka-attach doon, saka mamarkahan ang bawat
    assignment na phase="done" na may completed timestamp. Sinasaklaw
    parehong lumang single-machine bookings AT bagong multi-load
    bookings sa iisang function.

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id, for the same attribution reason as create_booking(). This
    is the endpoint used for status transitions including cancellation,
    so it's one of the more important actions to attribute correctly.

    NEW (Notifications): kung ang booking na ito ay may naka-attach na
    customer_id (galing sa mobile app), gumagawa ito ng isang
    Notification para sa customer, na may sariling type/title/message
    depende sa SPECIFIC na bagong status (see
    _get_status_notification_content() sa itaas). Wala itong ginagawang
    notification kung terminal-only ang booking (walang customer_id) o
    kung ang bagong status ay wala sa content_map (hal. "Pending").
    """
    shop_id = current_user.shop_id

    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.shop_id == shop_id
    ).first()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction record not found."
        )

    old_status = booking.status
    booking.status = new_status

    if new_status in ["Ready", "Claimed", "Cancelled"]:
        # --- Legacy single-machine release (washer_id/dryer_id) ---
        legacy_assigned_ids = [
            m_id for m_id in [booking.washer_id, booking.dryer_id]
            if m_id is not None
        ]
        if legacy_assigned_ids:
            legacy_machines = db.query(Machine).filter(
                Machine.id.in_(legacy_assigned_ids),
                Machine.shop_id == shop_id
            ).all()
            for machine in legacy_machines:
                _release_machine(machine)

        # --- NEW: multi-machine release (BookingMachineAssignment rows) ---
        assignments = (
            db.query(BookingMachineAssignment)
            .filter(BookingMachineAssignment.booking_id == booking.id)
            .all()
        )
        if assignments:
            machine_ids_to_release = set()
            for assignment in assignments:
                if assignment.washer_id:
                    machine_ids_to_release.add(assignment.washer_id)
                if assignment.dryer_id:
                    machine_ids_to_release.add(assignment.dryer_id)

                assignment.phase = "done"
                now = datetime.now(timezone.utc)
                if assignment.dryer_id and not assignment.drying_completed_at:
                    assignment.drying_completed_at = now
                elif assignment.washer_id and not assignment.washing_completed_at:
                    assignment.washing_completed_at = now

            if machine_ids_to_release:
                machines_to_release = db.query(Machine).filter(
                    Machine.id.in_(machine_ids_to_release),
                    Machine.shop_id == shop_id
                ).all()
                for machine in machines_to_release:
                    _release_machine(machine)

    try:
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=(
                f"Changed booking status for {booking.customer_name}: "
                f"{old_status} → {new_status}"
            )
        )

        if booking.customer_id:
            notif_content = _get_status_notification_content(new_status, booking)
            if notif_content:
                notif_type, notif_title, notif_message = notif_content
                notification_controller.create_notification(
                    db,
                    customer_id=booking.customer_id,
                    notif_type=notif_type,
                    title=notif_title,
                    message=notif_message,
                    booking_id=booking.id
                )

        db.commit()
        return (
            db.query(Booking)
            .options(
                joinedload(Booking.washer),
                joinedload(Booking.dryer),
                joinedload(Booking.inventory_usages),
                joinedload(Booking.add_ons_used),
                joinedload(Booking.machine_assignments),
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


# =========================================================
# PAYMENT FUNCTIONS
# =========================================================

def mark_booking_as_paid(db: Session, booking_id: int, payment_data: PaymentStatusUpdate, current_user: models.User):
    """
    Manual na "Mark as Paid" action ng staff. Ginagamit ito sa parehong
    Walk-in (cash, dropoff) at Mobile COD bookings, kung saan ang staff
    mismo ang nagko-confirm na natanggap na ang bayad — walang automated
    payment gateway verification pa dito (ang GCash/PayMaya QR +
    proof-upload na flow ay hiwalay na future phase).

    Staff mismo ang nagde-decide kung KAILAN i-mark bilang paid — walang
    naka-bind na fixed na timing (hal. pwede itong gawin bago pa man
    simulan ang laundry, o pagkatapos ng buong service, depende sa
    proseso ng bawat shop).

    Naka-scope sa parehong shop_id ng staff (current_user.shop_id) —
    hindi pwedeng i-mark ng isang shop ang booking ng ibang shop.
    """
    shop_id = current_user.shop_id

    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.shop_id == shop_id
    ).first()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found."
        )

    if booking.payment_status == "paid":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This booking is already marked as paid."
        )

    booking.payment_method = payment_data.payment_method
    booking.payment_status = "paid"
    booking.paid_at = datetime.now(timezone.utc)

    try:
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=(
                f"Marked booking for {booking.customer_name} as PAID "
                f"(via {payment_data.payment_method})"
            )
        )

        if booking.customer_id:
            notification_controller.create_notification(
                db,
                customer_id=booking.customer_id,
                notif_type="payment_confirmed",
                title="Payment Confirmed",
                message=(
                    f"Your payment for the {booking.service_type} booking at "
                    f"{booking.shop_name or 'the shop'} has been confirmed. Thank you!"
                ),
                booking_id=booking.id
            )

        db.commit()
        db.refresh(booking)
        return (
            db.query(Booking)
            .options(
                joinedload(Booking.washer),
                joinedload(Booking.dryer),
                joinedload(Booking.inventory_usages),
                joinedload(Booking.add_ons_used),
                joinedload(Booking.machine_assignments),
            )
            .filter(Booking.id == booking_id)
            .first()
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment Update Error: {str(e)}"
        )


# =========================================================
# CUSTOMER (MOBILE APP) BOOKING FUNCTIONS
# =========================================================

def _map_quantity_to_booking_fields(pricing_unit: str, quantity: float) -> dict:
    """
    Ang Booking table ay may weight/loads columns, hindi generic na
    "quantity" — dahil pareho itong ginagamit ng existing Booking Modal
    (web) sa halip na baguhin ang schema ng buong table, ito na lang ang
    i-map papunta sa tamang column base sa pricing_unit ng service:
      - "kg"    → weight = quantity, loads = 1
      - "load"  → loads = quantity, weight = 0.0 (hindi applicable)
      - "piece" → loads = quantity, weight = 0.0 (hindi applicable)
    """
    if pricing_unit == "kg":
        return {"weight": quantity, "loads": 1}
    return {"weight": 0.0, "loads": int(quantity)}


def _apply_promo_code(db: Session, shop_id: int, code: str, subtotal: float) -> tuple:
    """
    Nagva-validate ng promo code (active, not expired, may natitirang
    uses) at nagko-compute ng discount base sa subtotal. Kung invalid
    ang code (mali, expired, ubos na ang uses), raise HTTPException
    kaagad — hindi ito basta na lang ini-ignore, dahil ipinasok mismo
    ng customer ang code na 'to, dapat malaman nila kung bakit hindi
    gumana.

    Returns (promo_record, discount_amount) — 'yung promo_record ang
    ipapasa pabalik para ma-increment ang times_used pagkatapos
    ma-confirm na successful ang buong booking transaction.
    """
    promo = (
        db.query(PromoCode)
        .filter(
            PromoCode.shop_id == shop_id,
            PromoCode.code == code.strip().upper(),
            PromoCode.is_active == True
        )
        .first()
    )
    if not promo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Promo code '{code}' is invalid or no longer active."
        )
    if promo.expires_at and promo.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Promo code '{code}' has expired."
        )
    if promo.max_uses is not None and promo.times_used >= promo.max_uses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Promo code '{code}' has reached its usage limit."
        )

    if promo.discount_type == "percent":
        discount = subtotal * (promo.discount_value / 100)
    else:
        discount = promo.discount_value

    discount = min(discount, subtotal)
    return promo, round(discount, 2)


async def create_customer_booking(db: Session, customer: models.Customer, booking_data: CustomerBookingCreate):
    """
    Creates a booking INITIATED BY THE CUSTOMER via the mobile app.
    Unlike create_booking() (Service Terminal / staff), hindi agad ito
    "Pending" — nagsisimula ito sa status "Awaiting Approval" at
    kailangang tanggapin (Accept) o tanggihan (Decline) ng shop bago ito
    pumasok sa normal na Service Terminal flow.

    UPDATED: pinoproseso na rin ang fulfillment_mode (dropoff/delivery),
    add-ons, at promo code:
      1. base_price = service.price × quantity
      2. + add-ons total (mula sa add_on_ids, kada isa naka-validate na
         kabilang sa parehong shop at is_active)
      3. + delivery_fee (kung fulfillment_mode == "delivery", kinukuha
         mula sa Shop.delivery_fee; error kung ang shop pala ay
         Shop.has_delivery == False)
      4. − discount (kung may promo_code, naka-validate sa
         _apply_promo_code())
    Ang resultang total_price ang siyang naka-save sa Booking.

    UPDATED (Payment): ini-set na rin ang payment_method galing sa
    customer's checkout choice (booking_data.payment_method — "cash"
    para sa dropoff, "cod" para sa delivery, o "gcash"/"paymaya" kapag
    ini-enable na ang online payment sa future phase). payment_status
    ay laging nagsisimula bilang "unpaid" — ang pag-verify/pag-mark ay
    hiwalay pa ring action ng staff (see mark_booking_as_paid()).

    NOTE (multi-machine assignment feature): hindi pa rin dito nagaganap
    ang machine assignment — nananatiling "Awaiting Approval" muna, tapos
    "Pending" (via accept_customer_booking()), at doon pa lang ito
    aassignan ng machine gamit ang assign_machines_to_booking(), gaya rin
    ng manual bookings.

    NEW (safety net): bago pa man tingnan ang service catalog, sinusuri
    muna kung shop.is_online — ibig sabihin, may naka-buk as na Service
    Terminal ba ang shop na ito ngayon (see Shop.is_online sa models.py,
    na-update ng ws_manager.py sa connect()/disconnect()). Kung offline
    ang shop, walang talagang tatanggap/makakapag-accept ng booking na
    ito kahit ma-create pa ito, kaya sinasarhan na natin ito dito bago pa
    man mag-deduct ng anuman. Ito ang "totoong" hadlang — ang UI-level
    check (disabled na "Book Now" button sa mobile app) ay convenience
    lang, hindi ito dapat pag-asahan bilang tanging proteksyon, dahil
    puwede pa ring i-bypass ang UI (direktang API call, atbp.).

    Broadcasts a real-time WebSocket notification to the shop's connected
    Service Terminal instance(s) after a successful commit.
    """
    shop = db.query(models.Shop).filter(models.Shop.id == booking_data.shop_id).first()
    if not shop or not shop.is_published:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop not found."
        )

    if not shop.is_online:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This shop is currently closed and cannot accept new bookings. Please try again once the shop is open."
        )

    service_type_record = (
        db.query(ServiceType)
        .filter(
            ServiceType.shop_id == booking_data.shop_id,
            ServiceType.name == booking_data.service_type,
            ServiceType.is_active == True
        )
        .first()
    )
    if not service_type_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Service type '{booking_data.service_type}' is not available at this shop."
        )

    mapped_fields = _map_quantity_to_booking_fields(
        service_type_record.pricing_unit, booking_data.quantity
    )

    if service_type_record.pricing_unit == "kg":
        settings = db.query(Setting).filter(Setting.shop_id == booking_data.shop_id).first()
        minimum_weight = (settings.minimum_weight_kg if settings else None) or 6.0
        if mapped_fields["weight"] < minimum_weight:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Minimum booking weight is {minimum_weight}kg. Please adjust the quantity."
            )

    delivery_fee_charged = 0.0
    if booking_data.fulfillment_mode == "delivery":
        if not shop.has_delivery:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This shop does not offer delivery. Please choose drop-off instead."
            )
        delivery_fee_charged = shop.delivery_fee

    validated_add_ons = []
    add_ons_total = 0.0
    for add_on_id in booking_data.add_on_ids:
        add_on = (
            db.query(AddOn)
            .filter(
                AddOn.id == add_on_id,
                AddOn.shop_id == booking_data.shop_id,
                AddOn.is_active == True
            )
            .first()
        )
        if not add_on:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Add-on ID {add_on_id} is not available at this shop."
            )
        validated_add_ons.append((add_on, add_on.price))
        add_ons_total += add_on.price

    base_price = round(service_type_record.price * booking_data.quantity, 2)
    subtotal = round(base_price + add_ons_total + delivery_fee_charged, 2)

    promo_record = None
    discount_amount = 0.0
    if booking_data.promo_code:
        promo_record, discount_amount = _apply_promo_code(
            db, booking_data.shop_id, booking_data.promo_code, subtotal
        )

    total_price = round(subtotal - discount_amount, 2)

    new_booking = Booking(
        customer_name=customer.full_name,
        service_type=booking_data.service_type,
        category="Mobile App",
        weight=mapped_fields["weight"],
        loads=mapped_fields["loads"],
        total_price=total_price,
        booking_mode="customer",
        status="Awaiting Approval",
        shop_id=booking_data.shop_id,
        customer_id=customer.id,
        source="mobile",
        special_instructions=booking_data.special_instructions,
        fulfillment_mode=booking_data.fulfillment_mode,
        pickup_datetime=booking_data.pickup_datetime,
        delivery_fee_charged=delivery_fee_charged,
        promo_code=promo_record.code if promo_record else None,
        discount_amount=discount_amount,
        payment_method=booking_data.payment_method or "cash",
        booking_timestamp=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc)
    )

    try:
        db.add(new_booking)
        db.flush()

        for add_on, price_at_booking in validated_add_ons:
            db.add(BookingAddOnUsage(
                booking_id=new_booking.id,
                add_on_id=add_on.id,
                price_at_booking=price_at_booking
            ))

        if promo_record:
            promo_record.times_used += 1

        db.commit()
        db.refresh(new_booking)

        reloaded = (
            db.query(Booking)
            .options(
                joinedload(Booking.washer),
                joinedload(Booking.dryer),
                joinedload(Booking.inventory_usages),
                joinedload(Booking.add_ons_used),
                joinedload(Booking.machine_assignments),
            )
            .filter(Booking.id == new_booking.id)
            .first()
        )

        await manager.broadcast(booking_data.shop_id, {
            "type": "new_booking_request",
            "booking_id": reloaded.id,
            "customer_name": reloaded.customer_name,
            "service_type": reloaded.service_type,
            "total_price": reloaded.total_price,
            "quantity": booking_data.quantity,
            "pricing_unit": service_type_record.pricing_unit,
            "fulfillment_mode": reloaded.fulfillment_mode,
        })

        return reloaded
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database Transactional Error: {str(e)}"
        )


def get_awaiting_approval_bookings(db: Session, shop_id: int):
    """
    Retrieves customer-submitted bookings still waiting for the shop's
    Accept/Decline decision. Backs the notification panel on the web app.
    NOTE: read-only, no Activity Log entry.
    """
    return (
        db.query(Booking)
        .options(
            joinedload(Booking.inventory_usages),
            joinedload(Booking.add_ons_used)
        )
        .filter(
            Booking.shop_id == shop_id,
            Booking.status == "Awaiting Approval"
        )
        .order_by(Booking.booking_timestamp.desc())
        .all()
    )


def get_customer_bookings(db: Session, customer_id: int):
    """
    NEW — Retrieves EVERY booking made by a given customer, across ALL
    shops, any status — the data behind the mobile app's History page
    (and, if reused, a Notifications page). Most recent first.

    NOTE: read-only, no Activity Log entry (Activity Log is a shop-side
    accountability trail — this is the customer looking at their own
    data, not an action being performed on the shop's behalf).

    Booking.shop is lazy="joined" (see models.py) so the shop_name
    property is populated without triggering a separate query per
    booking, even though this list can span many different shops.
    """
    return (
        db.query(Booking)
        .options(
            joinedload(Booking.washer),
            joinedload(Booking.dryer),
            joinedload(Booking.inventory_usages),
            joinedload(Booking.add_ons_used),
            joinedload(Booking.machine_assignments),
        )
        .filter(Booking.customer_id == customer_id)
        .order_by(Booking.booking_timestamp.desc())
        .all()
    )


def accept_customer_booking(db: Session, booking_id: int, current_user: models.User):
    """
    Accepts a customer-submitted booking — moves it from "Awaiting
    Approval" to "Pending", at which point it behaves exactly like any
    manually-created booking (appears in the Service Terminal, can be
    assigned machine(s) via assign_machines_to_booking()).

    NEW (Notification): gumagawa rin ito ngayon ng "booking_accepted"
    notification para sa customer, para malaman nila agad (sa
    Notification Page + bell badge) na tinanggap na ng shop ang
    kanilang request.
    """
    shop_id = current_user.shop_id

    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.shop_id == shop_id,
        Booking.status == "Awaiting Approval"
    ).first()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking request not found or already handled."
        )

    booking.status = "Pending"

    try:
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=f"Accepted mobile booking request from {booking.customer_name} - {booking.service_type}"
        )

        if booking.customer_id:
            notification_controller.create_notification(
                db,
                customer_id=booking.customer_id,
                notif_type="booking_accepted",
                title="Booking Accepted",
                message=(
                    f"Good news! Your {booking.service_type} booking at "
                    f"{booking.shop_name or 'the shop'} has been accepted and is now being processed."
                ),
                booking_id=booking.id
            )

        db.commit()
        db.refresh(booking)
        return booking
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error accepting booking: {str(e)}"
        )

def get_all_bookings(db: Session, shop_id: int):
    """
    NEW — Retrieves EVERY booking for this shop, any status, most recent
    first. Backs the Record Sales page's bookings table (Date, Customer,
    Service, Payment). Read-only, no Activity Log entry.
    """
    return (
        db.query(Booking)
        .filter(Booking.shop_id == shop_id)
        .order_by(Booking.booking_timestamp.desc())
        .all()
    )


def decline_customer_booking(db: Session, booking_id: int, reason: str, current_user: models.User):
    """
    Declines a customer-submitted booking — moves it to "Declined".
    Kept in the database (not deleted) so it stays visible in the
    Activity Log/history, but it will never appear in the Service
    Terminal's active bookings list (see get_active_bookings() filter).

    NEW: now REQUIRES a `reason` (see BookingDeclineRequest validator —
    the empty-string case never reaches here). Saved onto
    Booking.decline_reason so the customer can see WHY their request was
    declined (e.g. "Fully booked") the next time they check the booking
    in the mobile app, instead of just seeing a bare "Declined" status.
    Also folded into the Activity Log description for the shop's own
    history/accountability.

    NEW (Notification): gumagawa rin ito ngayon ng "booking_declined"
    notification para sa customer, kasama ang parehong `reason` sa
    message — hindi na nila kailangang pumunta pa sa History page para
    lang malaman kung bakit hindi natuloy ang booking nila.
    """
    shop_id = current_user.shop_id

    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.shop_id == shop_id,
        Booking.status == "Awaiting Approval"
    ).first()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking request not found or already handled."
        )

    booking.status = "Declined"
    booking.decline_reason = reason

    try:
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=(
                f"Declined mobile booking request from {booking.customer_name} "
                f"- {booking.service_type} (Reason: {reason})"
            )
        )

        if booking.customer_id:
            notification_controller.create_notification(
                db,
                customer_id=booking.customer_id,
                notif_type="booking_declined",
                title="Booking Declined",
                message=(
                    f"Unfortunately, your {booking.service_type} booking at "
                    f"{booking.shop_name or 'the shop'} was declined. Reason: {reason}"
                ),
                booking_id=booking.id
            )

        db.commit()
        db.refresh(booking)
        return booking
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error declining booking: {str(e)}"
        )


async def cancel_customer_booking(db: Session, booking_id: int, customer: models.Customer):
    """
    NEW — Kinakansela ng CUSTOMER mismo (mobile app) ang sarili nilang
    booking. Pinapayagan lang ito habang ang status ay "Awaiting
    Approval" o "Pending" — sa dalawang puntong ito, wala pang aktibong
    machine cycle/resources na ginagamit ng shop para dito. Kapag
    "In Progress" na (naka-assign na ng washer/dryer, umiikot na ang
    machine), hindi na ito basta pwedeng kanselahin mula sa app —
    kailangan nang direktang kausapin ang shop, dahil may naikuha nang
    hardware resource ang shop para dito.

    Naka-scope sa Booking.customer_id == customer.id (hindi lang
    booking_id) para hindi makakansela ang isang customer ng booking ng
    ibang tao sa pamamagitan lang ng pag-guess ng ID.

    Gumagawa rin ito ng notification PARA SA CUSTOMER MISMO (type
    "booking_cancelled") bilang kumpirmasyon na naitala ang kanilang
    pagkansela, at nagbo-broadcast sa Service Terminal (WebSocket) para
    agad na malaman ng shop kung meron.
    """
    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.customer_id == customer.id
    ).first()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found."
        )

    cancellable_statuses = ["Awaiting Approval", "Pending"]
    if booking.status not in cancellable_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"This booking can no longer be cancelled (current status: "
                f"'{booking.status}'). Please contact the shop directly."
            )
        )

    old_status = booking.status
    booking.status = "Cancelled"

    assigned_ids = [m_id for m_id in [booking.washer_id, booking.dryer_id] if m_id is not None]
    if assigned_ids:
        machines = db.query(Machine).filter(
            Machine.id.in_(assigned_ids),
            Machine.shop_id == booking.shop_id
        ).all()
        for machine in machines:
            _release_machine(machine)

    try:
        log_activity(
            db, booking.shop_id,
            actor_name=customer.full_name,
            actor_role="customer",
            description=(
                f"Customer cancelled their {old_status} booking - {booking.service_type}"
            )
        )

        notification_controller.create_notification(
            db,
            customer_id=customer.id,
            notif_type="booking_cancelled",
            title="Booking Cancelled",
            message=(
                f"You've cancelled your {booking.service_type} booking at "
                f"{booking.shop_name or 'the shop'}."
            ),
            booking_id=booking.id
        )

        db.commit()
        db.refresh(booking)

        reloaded = (
            db.query(Booking)
            .options(
                joinedload(Booking.washer),
                joinedload(Booking.dryer),
                joinedload(Booking.inventory_usages),
                joinedload(Booking.add_ons_used),
                joinedload(Booking.machine_assignments),
            )
            .filter(Booking.id == booking.id)
            .first()
        )

        await manager.broadcast(booking.shop_id, {
            "type": "booking_cancelled_by_customer",
            "booking_id": reloaded.id,
            "customer_name": reloaded.customer_name,
            "service_type": reloaded.service_type,
        })

        return reloaded
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error cancelling booking: {str(e)}"
        )