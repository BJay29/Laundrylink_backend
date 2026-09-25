from app.models import Booking, Machine, Setting, ServiceType, BookingInventoryUsage, AddOn, PromoCode, BookingAddOnUsage, BookingMachineAssignment, Address
from app.schemas import (
    BookingCreate, BookingAssignMachine, CustomerBookingCreate, PaymentStatusUpdate,
    MachineAssignmentInput, MoveLoadToDryerInput, PaymentRejectRequest,
    BookingFinalizePricingRequest, BookingSubmitPaymentProofRequest,
    RiderAssignmentInput,
)
from app.services.prediction_service import PredictionService
from app.services.ws_manager import (
    manager,
    EVENT_NEW_BOOKING_REQUEST,
    EVENT_BOOKING_CANCELLED_BY_CUSTOMER,
    EVENT_BOOKING_PRICE_FINALIZED,
)
from app.controller import inventory_controller
from app.controller import notification_controller
from app.controller.activity_controller import log_activity
from app import models
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timezone
from app.services.customer_ws_manager import customer_manager, EVENT_BOOKING_UPDATED


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

    UPDATED (live timer feature): machine.remaining_time now comes from
    the SERVICE's washer_duration_minutes or dryer_duration_minutes
    (whichever matches the machine's machine_type), not a single
    ServiceType.duration_minutes field (an earlier version tried a
    per-MACHINE configured_duration_minutes column instead — reverted).
    machine.cycle_started_at is also stamped here so the frontend can
    compute a live countdown instead of a static number that never
    ticks down on its own.

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

    UPDATED (Online Payment feature — GCash/PayMaya QR + Proof of
    Payment): kung ang payment_method ay "gcash" o "paymaya" AT may
    ibinigay na booking_data.proof_of_payment_url, ang INITIAL
    payment_status ay "pending_verification" sa halip na "unpaid" —
    ibig sabihin nag-upload na ang staff/customer ng resibo, hinihintay
    na lang i-verify ng shop (see get_pending_verification_bookings()
    at reject_payment() sa ibaba). Para sa "cash"/"cod", walang binago
    — "unpaid" pa rin ang default.

    NEW (walk-in promo code support): kung may booking_data.promo_code,
    ang booking_data.total_price ay tinuturing na PRE-DISCOUNT subtotal
    — ang totoong discount ay kino-compute DITO SA BACKEND gamit ang
    parehong _apply_promo_code() helper na ginagamit na ng mobile-app
    flow (create_customer_booking() sa ibaba), hindi trust-lang sa
    kung anong "final total" ang ipinasa ng client. Ito ang naka-save
    bilang Booking.total_price (net na ng discount), kasama ang
    Booking.promo_code at Booking.discount_amount para sa record-keeping
    (makikita sa Record Sales / Booking Details). Kung invalid/expired/
    ubos na ang code, mag-ra-raise agad ng HTTPException dito bago pa
    man magsimula ang booking creation.

    NOTE (Weighing / Finalize Pricing feature): WALANG binago dito —
    ang staff, sa Service Terminal, ay direktang naglalagay na ng
    ACTUAL na weight/presyo sa mismong paggawa ng booking (harapan,
    walang "estimate" na hiwalay). Kaya walang estimated_weight/
    estimated_price/final_weight/final_price na naise-set dito —
    ang buong konseptong iyon ay para lang sa MOBILE APP self-booking
    flow (create_customer_booking() + finalize_booking_pricing() sa
    ibaba), kung saan malayo ang customer sa shop kapag gumawa ng
    booking, kaya hula lang muna ang unang presyo.

    NEW (Order Tracking / Live Stepper feature): kung naka-assign na ng
    machine inline dito (assigned_ids non-empty, i.e. status ay agad na
    "In Progress"), sini-stamp na rin ang Booking.started_at sa parehong
    sandali — para tama agad ang "Washing In Progress" na timestamp sa
    stepper ng mobile app kahit sa mismong paggawa pa lang ng booking na-
    assign na agad ang machine.

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

    # NEW (Order Tracking / Live Stepper feature) — stamp started_at at
    # creation time itself if a machine is already assigned inline.
    initial_started_at = datetime.now(timezone.utc) if assigned_ids else None

    # --- 4.1 DETERMINE INITIAL PAYMENT STATUS (NEW — Online Payment feature) ---
    # "gcash"/"paymaya" + may proof of payment na naka-upload na →
    # "pending_verification" (naghihintay ng staff approval). Lahat ng
    # iba pa (cash/cod, o online pero walang proof pa) → "unpaid",
    # gaya ng dating default.
    initial_payment_status = "unpaid"
    if booking_data.payment_method == "online_qr" and booking_data.proof_of_payment_url:
        initial_payment_status = "pending_verification"

    # --- 4.5 APPLY PROMO CODE (NEW — walk-in promo support) ---
    # Mirrors the mobile-app flow's use of _apply_promo_code(): the
    # discount is ALWAYS computed server-side from booking_data.total_price
    # as the pre-discount subtotal, never trusting a client-computed
    # final number. Raises HTTPException immediately if the code is
    # invalid/expired/exhausted — same behavior as the mobile flow.
    promo_record = None
    discount_amount = 0.0
    final_total_price = booking_data.total_price

    if booking_data.promo_code:
        promo_record, discount_amount = _apply_promo_code(
            db, shop_id, booking_data.promo_code, booking_data.total_price
        )
        final_total_price = round(booking_data.total_price - discount_amount, 2)

    # --- 5. CREATE THE BOOKING RECORD ---
    new_booking = Booking(
        customer_name=booking_data.customer_name,
        service_type=booking_data.service_type,
        category=booking_data.category,
        weight=booking_data.weight,
        loads=booking_data.loads,
        total_price=final_total_price,
        booking_mode=booking_data.booking_mode,
        add_detergent=booking_data.add_detergent,
        add_delivery=booking_data.add_delivery,
        is_rush=booking_data.is_rush,
        status=initial_status,
        # NEW (Order Tracking / Live Stepper feature)
        started_at=initial_started_at,
        washer_id=booking_data.washer_id,
        dryer_id=booking_data.dryer_id,
        shop_id=shop_id,
        source="terminal",
        payment_method=booking_data.payment_method or "cash",
        # NEW (Online Payment feature)
        payment_status=initial_payment_status,
        proof_of_payment_url=booking_data.proof_of_payment_url,
        promo_code=promo_record.code if promo_record else None,
        discount_amount=discount_amount,
        booking_timestamp=actual_booking_time,
        created_at=datetime.now(timezone.utc)
    )

    # --- 6. UPDATE MACHINE TELEMETRY (legacy path — only if machines are
    #    assigned inline at creation, i.e. single-load bookings). Multi-
    #    load bookings should NOT pass washer_id/dryer_id here — they
    #    stay "Pending" and use assign_machines_to_booking() instead.
    #    NOTE: uses final_total_price (post-discount) so machine
    #    profitability telemetry reflects what the shop actually earned,
    #    not the pre-discount sticker price. ---
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
        machine.current_price = final_total_price
        machine.total_cycles += 1
        machine.remaining_time = (
            service_type_record.washer_duration_minutes
            if machine.machine_type == "Washer"
            else service_type_record.dryer_duration_minutes
        )
        machine.cycle_started_at = datetime.now(timezone.utc)

        overhead_data = PredictionService.get_overhead(db, shop_id, machine.machine_type)
        machine.accumulated_electricity += overhead_data.get("electricity_cost", 0.0)
        machine.accumulated_water += overhead_data.get("water_cost", 0.0)
        machine.accumulated_detergent += overhead_data.get("detergent_cost", 0.0)

        overhead_total = overhead_data.get("total_overhead", 0.0)
        net_profit = final_total_price - overhead_total
        machine.net_profit_accumulated += net_profit

        if final_total_price > 0:
            margin = (net_profit / final_total_price) * 100
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

        # NEW (walk-in promo support) — only increment usage AFTER the
        # booking transaction is about to be committed successfully,
        # same ordering the mobile-app flow follows.
        if promo_record:
            promo_record.times_used += 1

        machine_note = ""
        if assigned_ids:
            machine_note = f" (machine assigned, {len(assigned_ids)} unit/s)"
        promo_note = f" [Promo: {promo_record.code}, -₱{discount_amount}]" if promo_record else ""
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=(
                f"Created a booking for {booking_data.customer_name} "
                f"- {booking_data.service_type}, ₱{final_total_price}{machine_note}{promo_note}"
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


async def assign_machine_to_booking(db: Session, booking_id: int, assign_data: "BookingAssignMachine", current_user: models.User):
    """
    LEGACY (multi-machine assignment feature) — single washer + single
    dryer lang, isang beses lang. Iniwan ito nang buo, hindi tinanggal,
    para sa backward compatibility habang tinatapos ang paglipat ng buong
    frontend papunta sa bagong assign_machines_to_booking() /
    move_load_to_dryer() sa ibaba. Para sa BAGONG bookings, gamitin na
    ang bagong dalawang function na iyon sa halip nito.

    NEW (Order Tracking / Live Stepper feature): sini-stamp na rin ang
    Booking.started_at sa sandaling ito naging "In Progress" — parehong
    sandali ng transition, kaya inilalagay ito dito sa halip na sa
    isang generic na "on status change" helper.

    UPDATED (customer WebSocket — Booking & Order Tracking Flow Fix):
    now `async` — pushes a live "booking_updated" event to the
    customer's own device right after committing.
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

        if service_type_record:
            machine.remaining_time = (
                service_type_record.washer_duration_minutes
                if machine.machine_type == "Washer"
                else service_type_record.dryer_duration_minutes
            )
        else:
            machine.remaining_time = PredictionService.get_machine_runtime(machine.machine_type, booking.service_type)
        machine.cycle_started_at = datetime.now(timezone.utc)

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
    booking.started_at = datetime.now(timezone.utc)

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

        reloaded = (
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

        if reloaded.customer_id:
            await customer_manager.send_to_customer(reloaded.customer_id, {
                "type": EVENT_BOOKING_UPDATED,
                "booking_id": reloaded.id,
                "status": reloaded.status,
                "started_at": reloaded.started_at.isoformat() if reloaded.started_at else None,
                "estimated_completion_time": (
                    reloaded.estimated_completion_time.isoformat()
                    if reloaded.estimated_completion_time else None
                ),
            })

        return reloaded
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
    machine.cycle_started_at = datetime.now(timezone.utc)

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
    NEW — Shared helper for freeing up a machine back to "Available".
    Skips machines currently in Maintenance.
    """
    if machine.status != "Maintenance":
        machine.status = "Available"
        machine.remaining_time = 0
        machine.cycle_started_at = None
        machine.current_service_type = "None"
        machine.current_price = 0.0


async def assign_machines_to_booking(db: Session, booking_id: int, assign_data: MachineAssignmentInput, current_user: models.User):
    """
    NEW — Multi-machine assignment para sa isang Pending booking.

    UPDATED (customer WebSocket — Booking & Order Tracking Flow Fix):
    now `async` — pushes a live "booking_updated" event to the
    customer's device right after committing.
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

    target_type = "Dryer" if required_phases == "dry_only" else "Washer"
    initial_phase = "drying" if required_phases == "dry_only" else "washing"
    now = datetime.now(timezone.utc)

    if service_type_record:
        duration_minutes = (
            service_type_record.dryer_duration_minutes
            if target_type == "Dryer"
            else service_type_record.washer_duration_minutes
        )
    else:
        duration_minutes = PredictionService.get_machine_runtime(target_type, booking.service_type)

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
    booking.started_at = now

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

        reloaded = (
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

        if reloaded.customer_id:
            await customer_manager.send_to_customer(reloaded.customer_id, {
                "type": EVENT_BOOKING_UPDATED,
                "booking_id": reloaded.id,
                "status": reloaded.status,
                "started_at": reloaded.started_at.isoformat() if reloaded.started_at else None,
                "estimated_completion_time": (
                    reloaded.estimated_completion_time.isoformat()
                    if reloaded.estimated_completion_time else None
                ),
                "machine_assignments": [a.to_dict() for a in reloaded.machine_assignments],
            })

        return reloaded
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Machine Assignment Error: {str(e)}"
        )


async def move_load_to_dryer(db: Session, booking_id: int, load_number: int, move_data: MoveLoadToDryerInput, current_user: models.User):
    """
    NEW — "Move to Dryer" action para sa isang SPECIFIC LOAD lang.

    UPDATED (customer WebSocket — Booking & Order Tracking Flow Fix):
    now `async` — pushes a live "booking_updated" event, kasama ang
    updated `machine_assignments` (may `phase`) para makita ng mobile
    app yung "washing → drying" transition.
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
        service_type_record.dryer_duration_minutes
        if service_type_record
        else PredictionService.get_machine_runtime("Dryer", booking.service_type)
    )

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

        reloaded = (
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

        if reloaded.customer_id:
            await customer_manager.send_to_customer(reloaded.customer_id, {
                "type": EVENT_BOOKING_UPDATED,
                "booking_id": reloaded.id,
                "status": reloaded.status,
                "estimated_completion_time": (
                    reloaded.estimated_completion_time.isoformat()
                    if reloaded.estimated_completion_time else None
                ),
                "machine_assignments": [a.to_dict() for a in reloaded.machine_assignments],
            })

        return reloaded
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Move to Dryer Error: {str(e)}"
        )


def get_active_bookings(db: Session, shop_id: int):
    """
    Retrieves all non-finalized tasks for the Terminal UI.
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
            Booking.status.notin_([
                "Claimed", "Cancelled", "Awaiting Approval", "Declined",
                "Awaiting Weighing", "Awaiting Payment",
            ])
        )
        .order_by(Booking.booking_timestamp.desc())
        .all()
    )


def _get_status_notification_content(new_status: str, booking: Booking):
    """
    NEW — Nagbabalik ng (type, title, message) tuple na naka-tugma sa
    PARTIKULAR na status na pinasok ng booking.
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


async def update_booking_status(db: Session, booking_id: int, new_status: str, current_user: models.User):
    """
    Manages the booking lifecycle and releases machine resources back to 'Available'.

    FIXED (Booking & Order Tracking Flow Fix — missing timestamps bug):
    dating hindi talaga naisa-stamp ang Booking.ready_at/completed_at
    dito, kahit sinasabi ng docstring ng klase (models.py) na "dito ito
    nangyayari" — resulta, permanenteng "Pending" ang mobile app's
    "Ready — Rider Returning" at "Completed" timeline nodes kahit tapos
    na talaga ang buong booking (estimated_completion_time property at
    machine-release logic gumagana pa rin nang tama, pero itong dalawang
    booking-level timestamp lang ang di na-set). Idinagdag na ngayon
    ang pagse-set: ready_at kapag papuntang "Ready", completed_at kapag
    papuntang "Claimed" — pareho lang isang beses lang, hindi
    ino-overwrite kung meron na (parehong pattern ng started_at sa
    ibang function dito).

    UPDATED (customer WebSocket): now `async` — pushes a live
    "booking_updated" event to the customer's own device (if connected)
    right after committing, in addition to the Notification row already
    created below (which the mobile app also polls as a fallback when
    it isn't currently connected).
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

    now = datetime.now(timezone.utc)

    # FIXED — stamp ready_at / completed_at at the exact moment of
    # transition, same pattern as started_at elsewhere in this file.
    if new_status == "Ready" and not booking.ready_at:
        booking.ready_at = now
    if new_status == "Claimed" and not booking.completed_at:
        booking.completed_at = now

    if new_status in ["Ready", "Claimed", "Cancelled"]:
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

        reloaded = (
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

        if reloaded.customer_id:
            await customer_manager.send_to_customer(reloaded.customer_id, {
                "type": EVENT_BOOKING_UPDATED,
                "booking_id": reloaded.id,
                "status": reloaded.status,
                "payment_status": reloaded.payment_status,
                "ready_at": reloaded.ready_at.isoformat() if reloaded.ready_at else None,
                "completed_at": reloaded.completed_at.isoformat() if reloaded.completed_at else None,
            })

        return reloaded
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Status Lifecycle Error: {str(e)}"
        )


# =========================================================
# PAYMENT FUNCTIONS
# =========================================================

async def mark_booking_as_paid(db: Session, booking_id: int, payment_data: PaymentStatusUpdate, current_user: models.User):
    """
    UPDATED (customer WebSocket): now `async` — pushes a live
    "booking_updated" event to the customer's device right after
    committing.
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

    if payment_data.payment_method is not None:
        booking.payment_method = payment_data.payment_method
    booking.payment_status = "paid"
    booking.paid_at = datetime.now(timezone.utc)

    if booking.status == "Awaiting Payment":
        booking.status = "Pending"

    try:
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=(
                f"Marked booking for {booking.customer_name} as PAID "
                f"(via {booking.payment_method})"
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

        reloaded = (
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

        if reloaded.customer_id:
            await customer_manager.send_to_customer(reloaded.customer_id, {
                "type": EVENT_BOOKING_UPDATED,
                "booking_id": reloaded.id,
                "status": reloaded.status,
                "payment_status": reloaded.payment_status,
            })

        return reloaded
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment Update Error: {str(e)}"
        )


async def reject_payment(db: Session, booking_id: int, reason: str, current_user: models.User):
    """
    UPDATED (customer WebSocket): now `async` — pushes a live
    "booking_updated" event to the customer's device right after
    committing.
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

    if booking.payment_status != "pending_verification":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot reject a payment with status '{booking.payment_status}'. "
                "Only payments awaiting verification can be rejected."
            )
        )

    booking.payment_status = "unpaid"
    booking.payment_rejection_reason = reason

    try:
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=(
                f"Rejected online payment proof for {booking.customer_name}'s booking "
                f"(Reason: {reason})"
            )
        )

        if booking.customer_id:
            notification_controller.create_notification(
                db,
                customer_id=booking.customer_id,
                notif_type="payment_rejected",
                title="Payment Rejected",
                message=(
                    f"Your payment proof for the {booking.service_type} booking at "
                    f"{booking.shop_name or 'the shop'} was rejected. Reason: {reason}. "
                    "Please upload a new proof of payment."
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
            .filter(Booking.id == booking_id)
            .first()
        )

        if reloaded.customer_id:
            await customer_manager.send_to_customer(reloaded.customer_id, {
                "type": EVENT_BOOKING_UPDATED,
                "booking_id": reloaded.id,
                "status": reloaded.status,
                "payment_status": reloaded.payment_status,
            })

        return reloaded
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment Rejection Error: {str(e)}"
        )


def get_pending_verification_bookings(db: Session, shop_id: int):
    """
    NEW (Online Payment feature) — Retrieves bookings ng shop na
    payment_status == "pending_verification".
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
            Booking.payment_status == "pending_verification"
        )
        .order_by(Booking.booking_timestamp.desc())
        .all()
    )

async def submit_payment_proof(
    db: Session,
    booking_id: int,
    proof_data: BookingSubmitPaymentProofRequest,
    customer: models.Customer,
):
    """
    NEW (Module C) — customer attaches proof of payment sa isang
    booking na "Awaiting Payment" na.
    """
    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.customer_id == customer.id,
    ).first()

    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found."
        )

    if booking.status != "Awaiting Payment":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot submit payment proof for a booking with status "
                f"'{booking.status}'. Only bookings Awaiting Payment can "
                "have proof submitted."
            )
        )

    booking.proof_of_payment_url = proof_data.proof_of_payment_url
    booking.payment_status = "pending_verification"

    try:
        log_activity(
            db, booking.shop_id,
            actor_name=customer.full_name,
            actor_role="customer",
            description=f"Customer submitted payment proof for their booking - {booking.service_type}"
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
            .filter(Booking.id == booking_id)
            .first()
        )

        await manager.broadcast(booking.shop_id, {
            "type": "new_payment_verification_request",
            "booking_id": reloaded.id,
            "customer_name": reloaded.customer_name,
        })

        await customer_manager.send_to_customer(customer.id, {
            "type": EVENT_BOOKING_UPDATED,
            "booking_id": reloaded.id,
            "status": reloaded.status,
            "payment_status": reloaded.payment_status,
        })

        return reloaded
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Submit Payment Proof Error: {str(e)}"
        )


# =========================================================
# WEIGHING / FINALIZE PRICING FUNCTIONS
# =========================================================

def get_awaiting_weighing_bookings(db: Session, shop_id: int):
    """
    NEW — Retrieves mobile bookings ng shop na status == "Awaiting
    Weighing".
    """
    return (
        db.query(Booking)
        .options(
            joinedload(Booking.inventory_usages),
            joinedload(Booking.add_ons_used),
        )
        .filter(
            Booking.shop_id == shop_id,
            Booking.status == "Awaiting Weighing"
        )
        .order_by(Booking.booking_timestamp.desc())
        .all()
    )


async def finalize_booking_pricing(
    db: Session,
    booking_id: int,
    pricing_data: BookingFinalizePricingRequest,
    current_user: models.User,
):
    """
    NEW — Core ng staff weighing/pricing modal.
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

    if booking.status != "Awaiting Weighing":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot finalize pricing for a booking with status '{booking.status}'. "
                "Only bookings that are Awaiting Weighing can be finalized."
            )
        )

    service_type_record = (
        db.query(ServiceType)
        .filter(
            ServiceType.shop_id == shop_id,
            ServiceType.name == booking.service_type
        )
        .first()
    )
    if not service_type_record:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Service type '{booking.service_type}' is no longer configured for this shop. "
                "Please check Optimization Settings."
            )
        )

    delivery_fee = booking.delivery_fee_charged or 0.0
    discount = booking.discount_amount or 0.0

    computed_price = round(
        (pricing_data.final_weight * service_type_record.price)
        + pricing_data.addon_charges
        + delivery_fee
        - discount,
        2
    )
    computed_price = max(0.0, computed_price)

    mapped_fields = _map_quantity_to_booking_fields(
        service_type_record.pricing_unit, pricing_data.final_weight
    )

    booking.final_weight = pricing_data.final_weight
    booking.weighing_addon_charges = pricing_data.addon_charges
    booking.final_price = computed_price
    booking.weighed_at = datetime.now(timezone.utc)

    booking.weight = mapped_fields["weight"]
    booking.loads = mapped_fields["loads"]
    booking.total_price = computed_price

    is_online_payment = booking.payment_method == "online_qr"
    booking.status = "Awaiting Payment" if is_online_payment else "Pending"

    try:
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=(
                f"Finalized pricing for {booking.customer_name}'s booking "
                f"- {pricing_data.final_weight} weighed, ₱{computed_price} "
                f"(addons: ₱{pricing_data.addon_charges})"
            )
        )

        if booking.customer_id:
            if is_online_payment:
                notif_title = "Ready for Payment!"
                notif_message = (
                    f"Your {booking.service_type} laundry at {booking.shop_name or 'the shop'} "
                    f"has been weighed ({pricing_data.final_weight}). Final total is "
                    f"₱{computed_price}. Please settle your payment."
                )
            else:
                notif_title = "Weighed — Now In Progress"
                notif_message = (
                    f"Your {booking.service_type} laundry at {booking.shop_name or 'the shop'} "
                    f"has been weighed ({pricing_data.final_weight}). Final total is "
                    f"₱{computed_price}."
                )
            notification_controller.create_notification(
                db,
                customer_id=booking.customer_id,
                notif_type="price_finalized",
                title=notif_title,
                message=notif_message,
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
            .filter(Booking.id == booking_id)
            .first()
        )

        await manager.broadcast(shop_id, {
            "type": EVENT_BOOKING_PRICE_FINALIZED,
            "booking_id": reloaded.id,
            "customer_name": reloaded.customer_name,
            "final_weight": reloaded.final_weight,
            "final_price": reloaded.final_price,
            "status": reloaded.status,
        })
        if reloaded.customer_id:
            await customer_manager.send_to_customer(reloaded.customer_id, {
                "type": EVENT_BOOKING_UPDATED,
                "booking_id": reloaded.id,
                "status": reloaded.status,
                "payment_status": reloaded.payment_status,
                "final_weight": reloaded.final_weight,
                "final_price": reloaded.final_price,
            })

        return reloaded
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Finalize Pricing Error: {str(e)}"
        )


# =========================================================
# RIDER ASSIGNMENT FUNCTIONS
# =========================================================

async def assign_pickup_rider(
    db: Session,
    booking_id: int,
    rider_data: RiderAssignmentInput,
    current_user: models.User,
):
    """
    NEW — Itinatakda ng staff ang pangalan at contact number ng rider
    na kukuha ng maruming damit sa bahay ng customer.

    UPDATED (customer WebSocket — Booking & Order Tracking Flow Fix):
    now `async` — dagdag live push.
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

    if booking.fulfillment_mode != "delivery":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rider assignment only applies to delivery bookings, not drop-off."
        )

    non_assignable_statuses = ["Awaiting Approval", "Declined", "Claimed", "Cancelled"]
    if booking.status in non_assignable_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot assign a pickup rider to a booking with status '{booking.status}'."
        )

    booking.pickup_rider_name = rider_data.rider_name
    booking.pickup_rider_contact = rider_data.rider_contact
    booking.pickup_rider_assigned_at = datetime.now(timezone.utc)

    try:
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=(
                f"Assigned pickup rider {rider_data.rider_name} "
                f"({rider_data.rider_contact}) to {booking.customer_name}'s booking"
            )
        )

        if booking.customer_id:
            notification_controller.create_notification(
                db,
                customer_id=booking.customer_id,
                notif_type="pickup_rider_assigned",
                title="Rider On The Way",
                message=(
                    f"{rider_data.rider_name} ({rider_data.rider_contact}) is on the way "
                    f"to pick up your laundry for your booking at "
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
            .filter(Booking.id == booking_id)
            .first()
        )

        if reloaded.customer_id:
            await customer_manager.send_to_customer(reloaded.customer_id, {
                "type": EVENT_BOOKING_UPDATED,
                "booking_id": reloaded.id,
                "status": reloaded.status,
                "pickup_rider_name": reloaded.pickup_rider_name,
                "pickup_rider_contact": reloaded.pickup_rider_contact,
            })

        return reloaded
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pickup Rider Assignment Error: {str(e)}"
        )


async def assign_delivery_rider(
    db: Session,
    booking_id: int,
    rider_data: RiderAssignmentInput,
    current_user: models.User,
):
    """
    NEW — Itinatakda ng staff ang pangalan at contact number ng rider
    na maghahatid ng malinis na laundry pabalik sa customer.
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

    if booking.fulfillment_mode != "delivery":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rider assignment only applies to delivery bookings, not drop-off."
        )

    assignable_statuses = ["In Progress", "Ready"]
    if booking.status not in assignable_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Cannot assign a delivery rider to a booking with status "
                f"'{booking.status}'. The laundry must be In Progress or Ready first."
            )
        )

    booking.delivery_rider_name = rider_data.rider_name
    booking.delivery_rider_contact = rider_data.rider_contact
    booking.delivery_rider_assigned_at = datetime.now(timezone.utc)

    try:
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.role,
            actor_role=current_user.role,
            description=(
                f"Assigned delivery rider {rider_data.rider_name} "
                f"({rider_data.rider_contact}) to {booking.customer_name}'s booking"
            )
        )

        if booking.customer_id:
            notification_controller.create_notification(
                db,
                customer_id=booking.customer_id,
                notif_type="delivery_rider_assigned",
                title="Laundry On The Way",
                message=(
                    f"{rider_data.rider_name} ({rider_data.rider_contact}) is on the way "
                    f"to deliver your clean laundry from {booking.shop_name or 'the shop'}."
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
            .filter(Booking.id == booking_id)
            .first()
        )

        if reloaded.customer_id:
            await customer_manager.send_to_customer(reloaded.customer_id, {
                "type": EVENT_BOOKING_UPDATED,
                "booking_id": reloaded.id,
                "status": reloaded.status,
                "delivery_rider_name": reloaded.delivery_rider_name,
                "delivery_rider_contact": reloaded.delivery_rider_contact,
            })

        return reloaded
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Delivery Rider Assignment Error: {str(e)}"
        )


# =========================================================
# CUSTOMER (MOBILE APP) BOOKING FUNCTIONS
# =========================================================

def _map_quantity_to_booking_fields(pricing_unit: str, quantity: float) -> dict:
    """
    Ang Booking table ay may weight/loads columns, hindi generic na
    "quantity".
    """
    if pricing_unit == "kg":
        return {"weight": quantity, "loads": 1}
    return {"weight": 0.0, "loads": int(quantity)}


def _apply_promo_code(db: Session, shop_id: int, code: str, subtotal: float) -> tuple:
    """
    Nagva-validate ng promo code at nagko-compute ng discount base sa
    subtotal.
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


def preview_promo_code(db: Session, shop_id: int, code: str, subtotal: float) -> dict:
    """
    NEW (Real-time Promo Preview feature) — customer-facing, NON-
    MUTATING "dry run" ng _apply_promo_code().
    """
    cleaned_code = (code or "").strip().upper()

    if not cleaned_code:
        return {
            "valid": False,
            "code": cleaned_code,
            "message": None,
            "discount_type": None,
            "discount_value": None,
            "discount_amount": 0.0,
            "final_total": round(subtotal, 2),
        }

    try:
        promo_record, discount_amount = _apply_promo_code(db, shop_id, cleaned_code, subtotal)
    except HTTPException as e:
        return {
            "valid": False,
            "code": cleaned_code,
            "message": e.detail if isinstance(e.detail, str) else "Invalid promo code.",
            "discount_type": None,
            "discount_value": None,
            "discount_amount": 0.0,
            "final_total": round(subtotal, 2),
        }

    return {
        "valid": True,
        "code": promo_record.code,
        "message": None,
        "discount_type": promo_record.discount_type,
        "discount_value": promo_record.discount_value,
        "discount_amount": discount_amount,
        "final_total": round(subtotal - discount_amount, 2),
    }


async def create_customer_booking(db: Session, customer: models.Customer, booking_data: CustomerBookingCreate):
    """
    Creates a booking INITIATED BY THE CUSTOMER via the mobile app.
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
    delivery_address_record = None
    if booking_data.fulfillment_mode == "delivery":
        if not shop.has_delivery:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This shop does not offer delivery. Please choose drop-off instead."
            )
        delivery_fee_charged = shop.delivery_fee

        delivery_address_record = (
            db.query(Address)
            .filter(
                Address.id == booking_data.address_id,
                Address.customer_id == customer.id,
            )
            .first()
        )
        if not delivery_address_record:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selected delivery address was not found in your saved addresses."
            )

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

    initial_payment_status = "unpaid"
    if booking_data.payment_method == "online_qr" and booking_data.proof_of_payment_url:
        initial_payment_status = "pending_verification"

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
        delivery_address_id=delivery_address_record.id if delivery_address_record else None,
        delivery_address_line=delivery_address_record.address_line if delivery_address_record else None,
        delivery_latitude=delivery_address_record.latitude if delivery_address_record else None,
        delivery_longitude=delivery_address_record.longitude if delivery_address_record else None,
        promo_code=promo_record.code if promo_record else None,
        discount_amount=discount_amount,
        payment_method=booking_data.payment_method or "cash",
        payment_status=initial_payment_status,
        proof_of_payment_url=booking_data.proof_of_payment_url,
        estimated_weight=booking_data.quantity,
        estimated_price=total_price,
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
            "type": EVENT_NEW_BOOKING_REQUEST,
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
    Accept/Decline decision.
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
    shops, any status.
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


async def accept_customer_booking(db: Session, booking_id: int, current_user: models.User):
    """
    Accepts a customer-submitted booking.

    UPDATED (customer WebSocket — Booking & Order Tracking Flow Fix):
    now `async` — pushes a live "booking_updated" event right after
    committing.
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

    booking.status = "Awaiting Weighing"

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
                    f"{booking.shop_name or 'the shop'} has been accepted. The shop will "
                    "confirm the actual weight and final price shortly."
                ),
                booking_id=booking.id
            )

        db.commit()
        db.refresh(booking)

        if booking.customer_id:
            await customer_manager.send_to_customer(booking.customer_id, {
                "type": EVENT_BOOKING_UPDATED,
                "booking_id": booking.id,
                "status": booking.status,
            })

        return booking
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error accepting booking: {str(e)}"
        )

def get_all_bookings(db: Session, shop_id: int):
    """
    NEW — Retrieves EVERY booking for this shop, any status.
    """
    return (
        db.query(Booking)
        .filter(Booking.shop_id == shop_id)
        .order_by(Booking.booking_timestamp.desc())
        .all()
    )


async def decline_customer_booking(db: Session, booking_id: int, reason: str, current_user: models.User):
    """
    Declines a customer-submitted booking — moves it to "Declined".

    UPDATED (customer WebSocket — Booking & Order Tracking Flow Fix):
    now `async` — pushes a live "booking_updated" event.
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

        if booking.customer_id:
            await customer_manager.send_to_customer(booking.customer_id, {
                "type": EVENT_BOOKING_UPDATED,
                "booking_id": booking.id,
                "status": booking.status,
                "decline_reason": booking.decline_reason,
            })

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
    booking.
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
            "type": EVENT_BOOKING_CANCELLED_BY_CUSTOMER,
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