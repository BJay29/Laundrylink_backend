from app.models import Notification
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone


def create_notification(
    db: Session,
    customer_id: int,
    notif_type: str,
    title: str,
    message: str,
    booking_id: int = None
):
    """
    Central helper para gumawa ng bagong Notification record para sa
    isang customer. Tinatawag ito mula sa booking_controller.py sa mga
    sandali ng accept, decline, status update (in-progress/ready/
    claimed/cancelled), at self-cancel ng customer — bawat isa may
    sariling notif_type/title/message kaya IBA-IBA ang lalabas na
    notification (hindi na parehong "may update sa booking mo" na
    generic na mensahe paulit-ulit).

    NOTE: hindi ito nag-c-commit mismo — dinadagdag lang niya ang
    bagong Notification sa session (db.add) at ang CALLER
    (booking_controller) ang responsable sa db.commit(). Sa ganitong
    paraan, iisang atomic transaction ang buong booking update +
    notification creation — magkasabay silang mag-rollback kung may
    mag-fail sa gitna.
    """
    notification = Notification(
        customer_id=customer_id,
        booking_id=booking_id,
        type=notif_type,
        title=title,
        message=message,
        is_read=False,
        created_at=datetime.now(timezone.utc)
    )
    db.add(notification)
    return notification


def get_customer_notifications(db: Session, customer_id: int):
    """
    Retrieves ALL notifications ng isang customer, pinaka-bago muna.
    Ito ang datos sa likod ng Notification Page ng mobile app.
    """
    return (
        db.query(Notification)
        .filter(Notification.customer_id == customer_id)
        .order_by(Notification.created_at.desc())
        .all()
    )


def get_unread_count(db: Session, customer_id: int) -> int:
    """
    Bilang ng unread notifications ng isang customer — ito ang
    gagamitin ng bell icon sa top bar para malaman kung magpapakita
    ba ng tuldok/number badge, at kung ano ang bilang na lalabas dito.
    """
    return (
        db.query(Notification)
        .filter(
            Notification.customer_id == customer_id,
            Notification.is_read == False
        )
        .count()
    )


def mark_read(db: Session, notification_id: int, customer_id: int):
    """
    Minamarka ang isang specific notification bilang read. Naka-scope
    sa customer_id (hindi lang notification_id) para hindi mamarkahan
    ng isang customer ang notification ng ibang tao sa pamamagitan lang
    ng pag-guess ng ID.

    Nagbabalik ng {message, updated_count} — 0 kung ALREADY read na
    ito bago pa man tumawag (idempotent, hindi error), 1 kung na-mark
    na read dito lang.
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

    if notification.is_read:
        return {"message": "Notification was already marked as read.", "updated_count": 0}

    notification.is_read = True

    try:
        db.commit()
        return {"message": "Notification marked as read.", "updated_count": 1}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error marking notification as read: {str(e)}"
        )


def mark_all_read(db: Session, customer_id: int):
    """
    Minamarka LAHAT ng unread notifications ng customer bilang read
    nang sabay-sabay — hal. kapag binuksan ng customer ang Notification
    Page, awtomatikong nawawala ang unread badge/tuldok.

    Nagbabalik ng {message, updated_count} kung saan updated_count ay
    ang eksaktong bilang ng notifications na na-flip mula unread
    papuntang read (0 kung wala nang natitirang unread).
    """
    try:
        updated_count = (
            db.query(Notification)
            .filter(
                Notification.customer_id == customer_id,
                Notification.is_read == False
            )
            .update({"is_read": True})
        )
        db.commit()
        return {
            "message": f"Marked {updated_count} notification(s) as read.",
            "updated_count": updated_count
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error marking all notifications as read: {str(e)}"
        )