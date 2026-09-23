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


def assign_machine_to_booking(db: Session, booking_id: int, assign_data: "BookingAssignMachine", current_user: models.User):
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

    # NEW (duration-per-service-phase) — needed to pick the right
    # washer/dryer duration per machine below.
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

        # NEW (duration-per-service-phase) — pick washer_duration_minutes
        # or dryer_duration_minutes depending on THIS machine's type.
        # get_machine_runtime() is kept as a last-resort fallback only
        # if the service record itself is missing (e.g. deleted since
        # the booking was made).
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
    # NEW (Order Tracking / Live Stepper feature)
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

    UPDATED (duration-per-service-phase): duration_minutes is passed in
    by the caller, who has already picked the right value —
    ServiceType.washer_duration_minutes or dryer_duration_minutes
    depending on which phase this machine is entering. (An earlier
    version tried deriving it from a per-machine
    configured_duration_minutes column instead — reverted.) Also stamps
    cycle_started_at so the frontend can compute a live, ticking
    countdown instead of trusting a static remaining_time number.
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
    NEW — Shared helper for freeing up a machine back to "Available",
    same pattern as the release block inside update_booking_status().
    Skips machines currently in Maintenance (those stay in Maintenance
    regardless of booking lifecycle).

    UPDATED (live timer feature): also clears cycle_started_at —
    otherwise a freed machine's frontend timer would keep counting down
    (or show a stale negative time) against a cycle that no longer
    exists.
    """
    if machine.status != "Maintenance":
        machine.status = "Available"
        machine.remaining_time = 0
        machine.cycle_started_at = None
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

    NEW (Order Tracking / Live Stepper feature): sini-stamp na rin ang
    Booking.started_at sa parehong sandali na naging "In Progress" ang
    booking.
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

    # NEW (duration-per-service-phase) — resolve once, before the loop,
    # since every machine assigned here is the same target_type.
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
    # NEW (Order Tracking / Live Stepper feature)
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

    NOTE (Order Tracking / Live Stepper feature): hindi ito nagbabago ng
    Booking.status (nananatiling "In Progress" ang buong booking habang
    may loads na washing/drying pa) — kaya walang binabagong Booking-
    level timestamp dito, per-load lang ang mga timestamp
    (washing_completed_at, drying_started_at) na naka-tira na sa
    BookingMachineAssignment.
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

    # NEW (duration-per-service-phase) — duration for the dry phase
    # comes from THIS booking's ServiceType.dryer_duration_minutes.
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

    UPDATED (Weighing / Finalize Pricing feature): idinagdag din sa
    exclusion list ang "Awaiting Weighing" at "Awaiting Payment" — mga
    mobile booking na naka-accept na pero HINDI pa dapat pumasok sa
    machine-assignment queue:
      - "Awaiting Weighing": wala pang aktwal na weight/presyo, kaya
        walang kahit anong ma-a-assign na machine pa dito. Ipinapakita
        ito sa hiwalay na panel (see get_awaiting_weighing_bookings()
        sa ibaba), gamit ang finalize_booking_pricing() para tuluyan
        itong pumasok dito.
      - "Awaiting Payment": na-finalize na ang presyo pero online ang
        payment method at hindi pa nababayaran — sadyang hinahawakan
        muna bago pumasok sa operational queue (see mark_booking_as_paid()
        sa ibaba, doon nangyayari ang awtomatikong paglipat papuntang
        "Pending" kapag na-verify na ang bayad).

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
            Booking.status.notin_([
                "Claimed", "Cancelled", "Awaiting Approval", "Declined",
                # NEW (Weighing / Finalize Pricing feature)
                "Awaiting Weighing", "Awaiting Payment",
            ])
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


async def update_booking_status(db: Session, booking_id: int, new_status: str, current_user: models.User):
    """
    Manages the booking lifecycle and releases machine resources back to 'Available'.

    ... (walang binago sa dating docstring — see previous version) ...

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
            detail=f"Status Lifecycle Error: {str(e)}"
        )


# =========================================================
# PAYMENT FUNCTIONS
# =========================================================

async def mark_booking_as_paid(db: Session, booking_id: int, payment_data: PaymentStatusUpdate, current_user: models.User):
    """
    ... (walang binago sa dating docstring) ...

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
    ... (walang binago sa dating docstring) ...

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
    payment_status == "pending_verification", i.e. mga GCash/PayMaya
    booking na naka-upload na ng proof of payment pero hindi pa
    na-verify/na-approve/na-reject ng staff. Backs ang "Pending Payment
    Verification" panel/tab sa Service Terminal (PaymentVerificationModal).

    NOTE: hindi ito naka-scope sa Booking.status (Pending/In Progress/
    atbp.) — sinasadya, dahil ang payment verification ay HIWALAY na
    proseso mula sa booking lifecycle mismo (puwedeng "Awaiting Payment"
    o "Pending" pa rin ang booking status habang "pending_verification"
    ang payment). Read-only, walang Activity Log entry.
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
    booking na "Awaiting Payment" na (na-finalize na ng staff ang
    presyo, online ang payment method). Itinatakda ang payment_status
    sa "pending_verification" — parehong verification flow gaya ng
    create-time na gcash/paymaya + proof_of_payment_url branch
    (PaymentVerificationModal -> mark_booking_as_paid()/reject_payment()
    ang gagamitin ng staff dito rin).

    Naka-scope sa Booking.customer_id == customer.id, parehong pattern
    ng cancel_customer_booking().
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

        # Refreshes the shop's "Pending Payment Verification" bell
        # right away.
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
# WEIGHING / FINALIZE PRICING FUNCTIONS (NEW — reconciled mula sa
# Admin Dashboard spec, Module B: "Mobile Booking Notification &
# Pricing Modal")
# =========================================================

def get_awaiting_weighing_bookings(db: Session, shop_id: int):
    """
    NEW — Retrieves mobile bookings ng shop na status == "Awaiting
    Weighing", i.e. na-accept na ng shop (dating "Awaiting Approval")
    pero hindi pa na-timbang/na-finalize ang presyo. Backs ang bagong
    notification panel/modal (Module B) sa Service Terminal, kung saan
    ipapasok ng staff ang aktwal na weight + add-on charges bago
    tawagin ang finalize_booking_pricing() sa ibaba.

    Read-only, walang Activity Log entry — parehong pattern ng
    get_awaiting_approval_bookings() at get_pending_verification_bookings().
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
    NEW — Ito ang core ng Module B ("Mobile Booking Notification &
    Pricing Modal"). Tinatawag ito kapag na-timbang na ng staff ang
    aktwal na laundry ng isang mobile booking na "Awaiting Weighing",
    at ini-finalize na ang presyo bago ito pumasok sa normal na
    operational queue.

    COMPUTATION (FIXED — Delivery Fee + Promo bug):
        final_price = (final_weight × ServiceType.price)
                       + addon_charges
                       + booking.delivery_fee_charged
                       − booking.discount_amount

    kung saan ang ServiceType.price/pricing_unit ay ang PAREHONG "Shop
    Rate" na ginagamit sa buong ibang bahagi ng sistema (walang
    hiwalay/bagong rate field na idinagdag — see ServiceTypeBase
    docstring sa schemas.py). Ang delivery_fee_charged at
    discount_amount ay pareho nang naka-save sa booking simula pa noong
    creation (create_customer_booking()) — kinukuha lang sila dito, HINDI
    muling kino-compute, para manatiling tugma ang huling babayaran sa
    kung ano talaga ang ipinangako sa customer.

    Pagkatapos ma-compute:
      1. Isinasave ang final_weight, weighing_addon_charges, final_price,
         weighed_at.
      2. SINI-SYNC ang weight/loads/total_price (ang "authoritative"
         fields na ginagamit ng ibang existing code — Record Sales,
         machine telemetry, atbp.) papunta sa bagong values na ito,
         gamit ang PAREHONG _map_quantity_to_booking_fields() helper na
         ginagamit ng create_customer_booking() para tama ang pagmapa
         sa weight/loads depende sa pricing_unit ng service.
      3. Itinatakda ang susunod na status:
         - "gcash"/"paymaya" → "Awaiting Payment" (hinihintay pa ang
           customer magbayad/mag-upload ng proof; makikita ito sa
           get_active_bookings() ng Service Terminal LAMANG kapag
           na-mark na paid via mark_booking_as_paid(), na siyang
           awtomatikong lilipat papuntang "Pending").
         - "cash"/"cod" → "Pending" — direktang pumapasok agad sa
           Service Terminal machine-assignment queue (ito ang
           "auto-route to Service Terminal" para sa COD/Cash na
           hiningi ng spec).
      4. Gumagawa ng customer notification (type "price_finalized")
         — ito ang available na "push"-like mechanism ng kasalukuyang
         sistema (walang hiwalay na customer-side WebSocket/FCM channel
         na naka-configure; ang mobile app ay umaasa sa Notification
         table + polling ng GET /bookings/mine, parehong pattern ng
         lahat ng ibang status-change notification sa buong file na
         ito).
      5. Nagba-broadcast ng "booking_price_finalized" event papunta sa
         SHOP's connected Service Terminal instance(s) — kapaki-pakinabang
         ito para agad ma-refresh ng terminal ang Awaiting Weighing panel
         nang hindi na kailangang mag-poll.

    NOTE (Order Tracking / Live Stepper feature): hindi ito nagba-bago
    ng started_at/ready_at/completed_at — ang weighed_at (nasa itaas na)
    ang siyang ginagamit ng mobile app stepper bilang timestamp ng
    "Weighed / Price Ready" step.
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

    # FIXED (Delivery Fee + Promo bug): dating kinukuwenta lang dito ang
    # (final_weight × rate) + addon_charges — nawawala ang
    # booking.delivery_fee_charged at booking.discount_amount, kaya sa
    # sandaling ma-finalize ang presyo (staff weighing), NABURA na sa
    # final_price/total_price ang delivery fee at anumang promo discount
    # na dating naka-factor na sa ESTIMATED total nung una pang gawin
    # ang booking sa create_customer_booking(). Kinukuha na ngayon dito
    # ang parehong dalawang halaga MULA SA BOOKING MISMO (naka-save na
    # sila doon simula pa noong creation, hindi na kailangang muling
    # i-validate/i-recompute ang promo code dito) at isinasama sa
    # pinal na kuwenta.
    #
    # NOTE: ang discount_amount ay ang FIXED NA PISONG HALAGA na na-lock
    # in na noong una pang gawin ang booking (isinama na ang % discount
    # computation doon) — sinasadyang HINDI na muling kino-compute ang
    # % laban sa bagong (mas mataas o mas mababang) final subtotal, para
    # hindi magbago ang "ipinangakong" halaga ng discount sa customer sa
    # pagitan ng booking time at weighing time.
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

    # Sync the authoritative weight/loads fields the same way the mobile
    # checkout flow does, so downstream code (Record Sales, machine
    # telemetry) sees a value consistent with the service's pricing_unit.
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
# RIDER ASSIGNMENT FUNCTIONS (NEW — Pickup & Delivery feature)
# =========================================================
#
# Manual-entry lang, walang Rider table/model (see Booking docstring sa
# models.py para sa buong reasoning). Dalawang HIWALAY na function ang
# meron dahil magkaiba ang oras at konteksto ng pickup leg vs delivery
# leg:
#   - assign_pickup_rider(): tinatawag ng staff PAGKATAPOS ma-accept
#     ang isang delivery booking (o kahit kailan habang wala pang
#     laman ang "Ready"/"Claimed" status) — ito ang rider na kukuha ng
#     maruming damit sa bahay ng customer papunta sa shop.
#   - assign_delivery_rider(): tinatawag ng staff kapag naging "Ready"
#     na ang laundry — ito ang rider na maghahatid ng malinis na damit
#     pabalik sa customer.
#
# Pareho silang naka-scope kay fulfillment_mode == "delivery" —
# walang silbi ang rider assignment sa isang "dropoff" booking, dahil
# ang shop mismo ang pinupuntahan/kinukunan ng customer doon.

def assign_pickup_rider(
    db: Session,
    booking_id: int,
    rider_data: RiderAssignmentInput,
    current_user: models.User,
):
    """
    NEW — Itinatakda ng staff ang pangalan at contact number ng rider
    na kukuha ng maruming damit sa bahay ng customer, para sa isang
    "delivery" booking. Manual text-entry lang sa Service Terminal —
    walang naka-catalog na listahan ng riders, walang naka-login na
    rider account.

    Pinapayagan habang ANG BOOKING AY HINDI PA "Claimed"/"Cancelled"/
    "Declined"/"Awaiting Approval" — sinasadyang malawak ang saklaw
    (hindi lang "Awaiting Weighing") dahil maaaring gustong i-set agad
    ng staff ang pickup rider kaagad pagka-accept, bago pa man dumating
    ang rider sa shop para timbangin ang laundry.

    Puwede itong tawagin nang paulit-ulit (hal. nagbago ang rider na
    ipinadala) — hindi ito naka-lock pagkatapos ng unang assignment,
    laging pinapalitan ang laman ng pickup_rider_name/contact.

    Gumagawa ng customer notification (type "pickup_rider_assigned")
    at nagpu-push ng live "booking_updated" event papunta sa customer's
    device, parehong pattern ng ibang status-mutating function dito.
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
    na maghahatid ng malinis na laundry pabalik sa customer, para sa
    isang "delivery" booking. Pareho ang disenyo ng assign_pickup_
    rider() sa itaas (manual text-entry, walang Rider table).

    Pinapayagan habang ang booking status ay "Ready" o "In Progress"
    (puwedeng i-preassign habang tinatapos pa ang paglaba, para ready
    na agad ang dispatch sa sandaling matapos) — HINDI pinapayagan
    kapag "Claimed" na (tapos na ang buong transaksyon) o kapag wala
    pang laman/tinatanggap pa lang ang booking.

    UPDATED (customer WebSocket): `async` dahil nagpu-push ito ng live
    "booking_updated" event papunta sa customer's device pagkatapos
    ma-commit, parehong pattern ng ibang status-mutating async function
    sa file na ito (update_booking_status(), mark_booking_as_paid(),
    atbp.) — mahalaga ito rito dahil ito na mismo ang "Your laundry is
    on the way" na signal na hinihintay ng customer sa stepper.
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
            actor_name=current_user.full_name or current_user.email,
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
    "quantity" — dahil pareho itong ginagamit ng existing Booking Modal
    (web) sa halip na baguhin ang schema ng buong table, ito na lang ang
    i-map papunta sa tamang column base sa pricing_unit ng service:
      - "kg"    → weight = quantity, loads = 1
      - "load"  → loads = quantity, weight = 0.0 (hindi applicable)
      - "piece" → loads = quantity, weight = 0.0 (hindi applicable)

    NOTE (Weighing / Finalize Pricing feature): ginagamit na rin ito
    ngayon ng finalize_booking_pricing() sa itaas, hindi lang ng
    create_customer_booking() sa ibaba — parehong pattern ng pag-map,
    kaya iisa lang ang lohika ng "quantity → weight/loads" sa buong
    sistema.
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

    NOTE: ginagamit na rin ito ngayon ng create_booking() (walk-in
    promo support), hindi lang ng create_customer_booking() (mobile
    app) — parehong function, iisang validation/computation logic.
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
    ini-enable na ang online payment). payment_status ay depende sa
    parehong logic ng create_booking() (see below) — hiwalay pa ring
    action ng staff ang pag-verify/pag-reject (see mark_booking_as_paid()
    at reject_payment()).

    UPDATED (Online Payment feature — GCash/PayMaya QR + Proof of
    Payment): kung ang payment_method ay "gcash" o "paymaya" AT may
    ibinigay na booking_data.proof_of_payment_url (na-upload na ng
    customer papunta sa Supabase Storage bago tinawag ang endpoint na
    ito), ang INITIAL payment_status ay "pending_verification" sa
    halip na "unpaid" — parehong logic ng create_booking() sa itaas.

    UPDATED (Weighing / Finalize Pricing feature): ang total_price na
    kino-compute dito ay HINDI na ang FINAL na presyo — ito na ngayon
    ang ESTIMATE lang ng customer (naka-base sa quantity na kanilang
    ibinigay sa checkout, bago pa man timbangin nang aktwal). Ise-save
    ito RIN sa bagong Booking.estimated_weight/estimated_price
    (kasabay pa rin ng weight/loads/total_price, para hindi masira ang
    kahit anong existing display na umaasa doon habang wala pa itong
    na-fifinalize — see BookingResponse/Booking.to_dict()). Ang totoong
    FINAL na presyo ay itatakda na lang ng staff sa
    finalize_booking_pricing() sa itaas, PAGKATAPOS ma-accept ang
    booking na ito (see accept_customer_booking() sa ibaba, na
    naglilipat na ngayon papuntang "Awaiting Weighing" sa halip na
    deretsong "Pending").

    NOTE (multi-machine assignment feature): hindi pa rin dito nagaganap
    ang machine assignment — nananatiling "Awaiting Approval" muna, tapos
    "Awaiting Weighing" (via accept_customer_booking()), tapos "Pending"
    o "Awaiting Payment" (via finalize_booking_pricing()), at doon pa
    lang ito aassignan ng machine gamit ang assign_machines_to_booking(),
    gaya rin ng manual bookings.

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
    # NEW (Delivery Address feature) — snapshot fields, filled in only
    # when fulfillment_mode == "delivery" (see Booking docstring sa
    # models.py para sa buong paliwanag kung bakit snapshot).
    delivery_address_record = None
    if booking_data.fulfillment_mode == "delivery":
        if not shop.has_delivery:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This shop does not offer delivery. Please choose drop-off instead."
            )
        delivery_fee_charged = shop.delivery_fee

        # address_id is required for delivery (see CustomerBookingCreate
        # validator in schemas.py) — validate it belongs to THIS
        # customer, same ownership-scoping pattern as add-on/promo
        # validation elsewhere in this function.
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

    # NEW (Online Payment feature) — same logic as create_booking().
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
        # NEW (Delivery Address feature) — snapshot at booking time, not
        # a live FK lookup (see Booking docstring sa models.py).
        delivery_address_id=delivery_address_record.id if delivery_address_record else None,
        delivery_address_line=delivery_address_record.address_line if delivery_address_record else None,
        delivery_latitude=delivery_address_record.latitude if delivery_address_record else None,
        delivery_longitude=delivery_address_record.longitude if delivery_address_record else None,
        promo_code=promo_record.code if promo_record else None,
        discount_amount=discount_amount,
        payment_method=booking_data.payment_method or "cash",
        # NEW (Online Payment feature)
        payment_status=initial_payment_status,
        proof_of_payment_url=booking_data.proof_of_payment_url,
        # NEW (Weighing / Finalize Pricing feature) — ang customer's
        # sariling estimate, hiwalay sa weight/total_price sa itaas
        # (na magiging "current" na rin habang wala pang na-finalize).
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
    Accepts a customer-submitted booking.

    UPDATED (Weighing / Finalize Pricing feature): dating deretsong
    "Pending" ang tinutuluyan nito — ngayon papunta muna ito sa BAGONG
    "Awaiting Weighing" status. Dahilan: ang presyo/weight na dala ng
    mobile booking na ito ay ESTIMATE pa lang ng customer (walang
    aktwal na pagtimbang), kaya kailangan munang dumaan sa staff
    weighing/finalize-pricing step (finalize_booking_pricing() sa
    itaas) bago ito tuluyang maging isang normal na "Pending" booking
    na puwedeng bigyan ng machine.

    Kapag na-finalize na ang presyo, doon pa lang ito lilipat papuntang
    "Pending" (cash/cod) o "Awaiting Payment" (gcash/paymaya), at doon
    pa lang ito puwedeng bigyan ng machine gamit ang
    assign_machines_to_booking(), gaya rin ng manual bookings.

    NEW (Notification): gumagawa rin ito ngayon ng "booking_accepted"
    notification para sa customer, para malaman nila agad (sa
    Notification Page + bell badge) na tinanggap na ng shop ang
    kanilang request — na-update ang mensahe para banggitin na
    hihintayin pa nila ang staff na kumpirmahin ang aktwal na timbang.
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

    # UPDATED (Weighing / Finalize Pricing feature) — "Awaiting Weighing"
    # sa halip na deretsong "Pending".
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

    NOTE (Weighing / Finalize Pricing feature): sinasadyang HINDI pa
    isinama ang "Awaiting Weighing"/"Awaiting Payment" sa
    cancellable_statuses sa ibaba — hindi pa ito hiningi ng kasalukuyang
    spec, at nangangailangan ng dagdag na pag-iisip (hal. dapat bang
    puwedeng kanselahin ang isang naka-finalize nang presyo?) bago ito
    idagdag. Idudulog na lang ito bilang susunod na item kung kakailanganin.

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