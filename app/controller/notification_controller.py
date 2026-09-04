from app.models import Notification
from sqlalchemy.orm import Session
from fastapi import HTTPException, status


def create_notification(db: Session, customer_id: int, title: str, message: str, booking_id: int = None):
    """
    Creates a Notification row and adds it to the session — DOES NOT
    commit. This is intentional: create_notification() is always called
    from WITHIN another function's existing transaction (accepting a
    booking, declining it, updating its status, atbp. in
    booking_controller.py), and should be committed ATOMICALLY together
    with whatever booking change triggered it. If that outer transaction
    rolls back, the notification should roll back too — there should
    never be a notification for something that didn't actually happen.

    Silently does nothing if customer_id is None (i.e. the booking has
    no associated mobile customer — a staff/terminal-created booking).
    Callers don't need to check this themselves before calling.
    """
    if customer_id is None:
        return None

    notification = Notification(
        customer_id=customer_id,
        booking_id=booking_id,
        title=title,
        message=message
    )
    db.add(notification)
    return notification


def get_customer_notifications(db: Session, customer_id: int):
    """
    Retrieves every notification for a customer, most recent first.
    Read-only.
    """
    return (
        db.query(Notification)
        .filter(Notification.customer_id == customer_id)
        .order_by(Notification.created_at.desc())
        .all()
    )


def mark_notification_read(db: Session, notification_id: int, customer_id: int):
    """
    Marks a single notification as read. Scoped to customer_id so a
    customer can never mark (or even discover the existence of) another
    customer's notification by guessing an ID.
    """
    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.customer_id == customer_id
        )
        .first()
    )
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found."
        )

    if not notification.is_read:
        notification.is_read = True
        db.commit()
        db.refresh(notification)

    return notification


def mark_all_notifications_read(db: Session, customer_id: int) -> int:
    """
    Marks every UNREAD notification belonging to this customer as read
    in one bulk update — used by the "mark all as read" action on the
    Notifications page. Returns the number of rows actually updated
    (0 if there was nothing unread, which is a normal/expected outcome,
    not an error).
    """
    updated_count = (
        db.query(Notification)
        .filter(
            Notification.customer_id == customer_id,
            Notification.is_read == False  # noqa: E712 - SQLAlchemy requires `== False`, not `is False`
        )
        .update({"is_read": True}, synchronize_session=False)
    )
    db.commit()
    return updated_count