from app.models import Booking, Machine, Setting, ServiceType, BookingInventoryUsage, AddOn, PromoCode, BookingAddOnUsage
from app.schemas import BookingCreate, BookingAssignMachine, CustomerBookingCreate
from app.services.prediction_service import PredictionService
from app.services.ws_manager import manager
from app.controller import inventory_controller
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

    UPDATED: machine.remaining_time now comes from the shop's own
    configured ServiceType.duration_minutes instead of
    PredictionService.get_machine_runtime()'s hardcoded estimate — the
    Machine Monitoring card reflects what the shop owner actually set
    in Optimization Settings.

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id, so the action can be attributed to whoever actually
    performed it (current_user.full_name or current_user.email /
    current_user.role) instead of just knowing which shop it happened in.

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

    # --- 4. DETERMINE INITIAL STATUS ---
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
        booking_timestamp=actual_booking_time,
        created_at=datetime.now(timezone.utc)
    )

    # --- 6. UPDATE MACHINE TELEMETRY (only if machines are assigned) ---
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

        # UPDATED: use the shop's own configured duration for this
        # service instead of the generic PredictionService estimate.
        machine.remaining_time = service_type_record.duration_minutes

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
        db.flush()

        for item, quantity_used in deducted_items:
            db.add(BookingInventoryUsage(
                booking_id=new_booking.id,
                inventory_item_id=item.id,
                quantity_used=quantity_used
            ))

        # --- 7. ACTIVITY LOG ---
        # Nasa loob ito ng try block nang sinasadya — kasama ito sa
        # PAREHONG db.commit() sa ibaba. Kung mag-fail ang commit
        # (halimbawa DB error), mag-rollback din ang log entry — walang
        # "orphan log" na sasabihing may nagawang booking kahit hindi
        # pala talaga na-save.
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
                joinedload(Booking.add_ons_used)
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
    Assigns a washer and/or dryer to an existing Pending booking that has no machine.

    UPDATED: Looks up the booking's service_type in this shop's ServiceType
    catalog to get the configured duration_minutes. Falls back to
    PredictionService.get_machine_runtime() only if the service no longer
    exists in the catalog (e.g. it was deleted after the booking was made).

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id, for the same attribution reason as create_booking().

    NOTE: works the same for "Pending" bookings regardless of source
    (terminal or customer-accepted-from-mobile) — once a customer
    booking is Accepted, it becomes an ordinary "Pending" booking and
    can be assigned a machine exactly like any other.
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

    # Resolve the configured duration for this booking's service type
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

        assigned_machine_labels.append(f"{machine.machine_type} #{machine.machine_number}")

    if assign_data.washer_id is not None:
        booking.washer_id = assign_data.washer_id
    if assign_data.dryer_id is not None:
        booking.dryer_id = assign_data.dryer_id

    booking.status = "In Progress"

    try:
        # --- ACTIVITY LOG ---
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
                joinedload(Booking.add_ons_used)
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
            joinedload(Booking.add_ons_used)
        )
        .filter(
            Booking.shop_id == shop_id,
            Booking.status.notin_(["Claimed", "Cancelled", "Awaiting Approval", "Declined"])
        )
        .order_by(Booking.booking_timestamp.desc())
        .all()
    )


def update_booking_status(db: Session, booking_id: int, new_status: str, current_user: models.User):
    """
    Manages the booking lifecycle and releases machine resources back to 'Available'.

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id, for the same attribution reason as create_booking(). This
    is the endpoint used for status transitions including cancellation,
    so it's one of the more important actions to attribute correctly.
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
        # --- ACTIVITY LOG ---
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=(
                f"Changed booking status for {booking.customer_name}: "
                f"{old_status} → {new_status}"
            )
        )

        db.commit()
        return (
            db.query(Booking)
            .options(
                joinedload(Booking.washer),
                joinedload(Booking.dryer),
                joinedload(Booking.inventory_usages),
                joinedload(Booking.add_ons_used)
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

    # Hindi pwedeng lumagpas sa subtotal ang discount (walang negative total).
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

    # --- SAFETY NET: block bookings while the shop has no live Service
    # Terminal connection, regardless of what the client-side UI shows. ---
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

    # Minimum weight check applies only to per-kg services — per-load
    # and per-piece services don't use the weight field meaningfully.
    if service_type_record.pricing_unit == "kg":
        settings = db.query(Setting).filter(Setting.shop_id == booking_data.shop_id).first()
        minimum_weight = (settings.minimum_weight_kg if settings else None) or 6.0
        if mapped_fields["weight"] < minimum_weight:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Minimum booking weight is {minimum_weight}kg. Please adjust the quantity."
            )

    # --- DELIVERY MODE VALIDATION ---
    delivery_fee_charged = 0.0
    if booking_data.fulfillment_mode == "delivery":
        if not shop.has_delivery:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This shop does not offer delivery. Please choose drop-off instead."
            )
        delivery_fee_charged = shop.delivery_fee

    # --- ADD-ONS VALIDATION + PRICING ---
    validated_add_ons = []  # list of (AddOn, price_at_booking)
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

    # --- PRICE COMPUTATION ---
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
        booking_timestamp=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc)
    )

    try:
        db.add(new_booking)
        db.flush()  # kailangan para makuha ang new_booking.id bago mag-commit

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
                joinedload(Booking.add_ons_used)
            )
            .filter(Booking.id == new_booking.id)
            .first()
        )

        # --- WEBSOCKET BROADCAST ---
        # Tahimik lang ang epekto kung walang naka-connect na Service
        # Terminal ngayon (walang error) — GET /bookings/awaiting-approval
        # pa rin ang siguradong makikita ito sa susunod na refresh/load.
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


def accept_customer_booking(db: Session, booking_id: int, current_user: models.User):
    """
    Accepts a customer-submitted booking — moves it from "Awaiting
    Approval" to "Pending", at which point it behaves exactly like any
    manually-created booking (appears in the Service Terminal, can be
    assigned a machine via assign_machine_to_booking()).
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
        db.commit()
        db.refresh(booking)
        return booking
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error accepting booking: {str(e)}"
        )


def decline_customer_booking(db: Session, booking_id: int, current_user: models.User):
    """
    Declines a customer-submitted booking — moves it to "Declined".
    Kept in the database (not deleted) so it stays visible in the
    Activity Log/history, but it will never appear in the Service
    Terminal's active bookings list (see get_active_bookings() filter).
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

    try:
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=f"Declined mobile booking request from {booking.customer_name} - {booking.service_type}"
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