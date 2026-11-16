"""
RIDER CONTROLLER (NEW — Rider accounts)

Lahat ng ginagawa ng naka-login na rider (role="rider") sa sarili niyang
page: tingnan ang mga job na naka-assign sa kanya, i-confirm ang pickup,
simulan ang delivery, at i-confirm ang delivery.

Mga patakaran:
  - Sariling job lang: pickup_rider_id / delivery_rider_id ay dapat ang
    id ng rider na tumatawag. Hindi niya nakikita o nagagalaw ang job ng iba.
  - Hindi dito binabago ang presyo, machines, o pag-assign ng rider —
    staff pa rin ang gumagawa noon.
  - Ang "Out for Delivery" at "Claimed" ay dumadaan sa parehong
    booking_controller.update_booking_status() na ginagamit ng staff,
    kaya pareho ang notification, timestamp, at live push sa customer.
"""
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.models import Booking
from app.schemas import RiderDeliveredInput
from app.controller import booking_controller, notification_controller
from app.controller.activity_controller import log_activity
from app.services.customer_ws_manager import customer_manager, EVENT_BOOKING_UPDATED

ONLINE_METHODS = ("gcash", "paymaya", "online_qr")
DEAD_STATUSES = ("Declined", "Cancelled", "Awaiting Approval")


def _amount_due(booking: Booking) -> float:
    """Halagang kokolektahin sa pinto. 0 kapag bayad na o online na bayad."""
    if booking.payment_status == "paid":
        return 0.0
    if (booking.payment_method or "cash") in ONLINE_METHODS:
        return 0.0
    amount = booking.final_price if booking.final_price is not None else booking.total_price
    return round(float(amount or 0.0), 2)


def _job_dict(booking: Booking, leg: str, stage: str, action) -> dict:
    customer = booking.customer
    return {
        "booking_id": booking.id,
        "leg": leg,
        "stage": stage,
        "action": action,
        "status": booking.status,
        "customer_name": booking.customer_name,
        "customer_phone": customer.mobile_number if customer else None,
        "service_type": booking.service_type,
        "loads": booking.loads,
        "weight": booking.final_weight if booking.final_weight is not None else booking.weight,
        "address_line": booking.delivery_address_line,
        "latitude": booking.delivery_latitude,
        "longitude": booking.delivery_longitude,
        "special_instructions": booking.special_instructions,
        "payment_method": booking.payment_method,
        "payment_status": booking.payment_status,
        "collect_amount": _amount_due(booking) if leg == "delivery" else 0.0,
        "pickup_datetime": booking.pickup_datetime,
        "pickup_window": booking.pickup_window,
        "delivery_datetime": booking.delivery_datetime,
        "picked_up_at": booking.picked_up_at,
        "out_for_delivery_at": booking.out_for_delivery_at,
        "completed_at": booking.completed_at,
        "shop_name": booking.shop_name,
    }


def get_jobs(db: Session, rider: models.User, scope: str = "active"):
    """
    scope="active" → mga trabahong may kailangan pang gawin o hinihintay.
    scope="done"   → mga natapos na (pinakabago muna, hanggang 50).
    Isang booking ay puwedeng magbigay ng dalawang job (pickup + delivery)
    kung iisang rider ang pareho.
    """
    bookings = (
        db.query(Booking)
        .filter(
            Booking.shop_id == rider.shop_id,
            Booking.fulfillment_mode == "delivery",
            or_(Booking.pickup_rider_id == rider.id, Booking.delivery_rider_id == rider.id),
        )
        .order_by(Booking.id.desc())
        .limit(300)
        .all()
    )

    active, done = [], []
    for b in bookings:
        if b.status in DEAD_STATUSES:
            continue

        if b.pickup_rider_id == rider.id:
            if b.picked_up_at is None and b.status != "Claimed":
                active.append(_job_dict(b, "pickup", "pickup_pending", "picked_up"))
            else:
                done.append((b.picked_up_at or b.completed_at, _job_dict(b, "pickup", "picked_up", None)))

        if b.delivery_rider_id == rider.id:
            if b.status == "In Progress":
                active.append(_job_dict(b, "delivery", "waiting", None))
            elif b.status == "Ready":
                active.append(_job_dict(b, "delivery", "ready", "start_delivery"))
            elif b.status == "Out for Delivery":
                active.append(_job_dict(b, "delivery", "on_the_way", "delivered"))
            elif b.status == "Claimed":
                done.append((b.completed_at, _job_dict(b, "delivery", "done", None)))

    if scope == "done":
        done.sort(key=lambda x: x[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return [j for _, j in done[:50]]

    # Pinaka-urgent muna: on_the_way, ready, pickup_pending, waiting
    order = {"on_the_way": 0, "ready": 1, "pickup_pending": 2, "waiting": 3}
    active.sort(key=lambda j: order.get(j["stage"], 9))
    return active


def _get_own_booking(db: Session, rider: models.User, booking_id: int, leg: str) -> Booking:
    booking = db.query(Booking).filter(
        Booking.id == booking_id,
        Booking.shop_id == rider.shop_id,
    ).first()
    owner_id = booking.pickup_rider_id if (booking and leg == "pickup") else (
        booking.delivery_rider_id if booking else None
    )
    if not booking or owner_id != rider.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    if booking.fulfillment_mode != "delivery":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This is not a delivery booking.")
    return booking


async def mark_picked_up(db: Session, rider: models.User, booking_id: int):
    booking = _get_own_booking(db, rider, booking_id, "pickup")

    if booking.status in DEAD_STATUSES or booking.status == "Claimed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot pick up a booking with status '{booking.status}'."
        )
    if booking.picked_up_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already marked as picked up.")

    booking.picked_up_at = datetime.now(timezone.utc)
    name = rider.full_name or rider.email

    try:
        log_activity(
            db, rider.shop_id,
            actor_name=name,
            actor_role=rider.role,
            description=f"Rider picked up the laundry of {booking.customer_name}"
        )
        if booking.customer_id:
            notification_controller.create_notification(
                db,
                customer_id=booking.customer_id,
                notif_type="laundry_picked_up",
                title="Laundry Picked Up",
                message=(
                    f"{name} has picked up your laundry and is bringing it to "
                    f"{booking.shop_name or 'the shop'}."
                ),
                booking_id=booking.id,
            )
        db.commit()
        db.refresh(booking)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pickup Error: {str(e)}"
        )

    if booking.customer_id:
        await customer_manager.send_to_customer(booking.customer_id, {
            "type": EVENT_BOOKING_UPDATED,
            "booking_id": booking.id,
            "status": booking.status,
            "picked_up_at": booking.picked_up_at.isoformat(),
        })
    return {"message": "Pickup confirmed.", "booking_id": booking.id}


async def start_delivery(db: Session, rider: models.User, booking_id: int):
    _get_own_booking(db, rider, booking_id, "delivery")
    # Parehong validation at notification ng staff (dapat "Ready", delivery, may rider).
    await booking_controller.update_booking_status(db, booking_id, "Out for Delivery", rider)
    return {"message": "Delivery started.", "booking_id": booking_id}


async def mark_delivered(db: Session, rider: models.User, booking_id: int, data: RiderDeliveredInput):
    booking = _get_own_booking(db, rider, booking_id, "delivery")

    if booking.status != "Out for Delivery":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Start the delivery first before marking it delivered."
        )

    if booking.payment_status != "paid":
        method = (booking.payment_method or "cash")
        if method in ONLINE_METHODS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The online payment is not verified yet. Please contact the shop."
            )
        if not data.cash_collected:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Collect ₱{_amount_due(booking):,.2f} from the customer first, then confirm."
            )
        booking.payment_status = "paid"
        booking.paid_at = datetime.now(timezone.utc)
        log_activity(
            db, rider.shop_id,
            actor_name=rider.full_name or rider.email,
            actor_role=rider.role,
            description=(
                f"Rider collected ₱{_amount_due_snapshot(booking):,.2f} on delivery "
                f"from {booking.customer_name}"
            )
        )

    await booking_controller.update_booking_status(db, booking_id, "Claimed", rider)
    return {"message": "Delivered.", "booking_id": booking_id}


def _amount_due_snapshot(booking: Booking) -> float:
    amount = booking.final_price if booking.final_price is not None else booking.total_price
    return float(amount or 0.0)