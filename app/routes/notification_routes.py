from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import NotificationResponse, NotificationMarkReadResponse
from app.controller import notification_controller
from app import models
from app.security import get_current_customer

# Notification router — customer-facing (mobile app) only. There is no
# shop/staff-facing equivalent; the Service Terminal's own notification
# bell reads directly from GET /bookings/awaiting-approval instead (see
# booking_routes.py), which serves a different purpose (unactioned
# requests) than this (a read/unread event history for the customer).
router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"]
)


@router.get("/mine", response_model=List[NotificationResponse])
def get_my_notifications(
    current_customer: models.Customer = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    Returns every notification for the logged-in customer, most recent
    first. Backs the mobile app's Notifications page and the unread
    badge on the bell icon (badge count = number of entries here where
    is_read is False — computed client-side from this same list, no
    separate "count" endpoint needed).
    """
    return notification_controller.get_customer_notifications(db, current_customer.id)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
def mark_notification_read(
    notification_id: int,
    current_customer: models.Customer = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    Marks a single notification as read — called when the customer taps
    an individual notification in the list.
    """
    return notification_controller.mark_notification_read(db, notification_id, current_customer.id)


@router.patch("/mark-all-read", response_model=NotificationMarkReadResponse)
def mark_all_notifications_read(
    current_customer: models.Customer = Depends(get_current_customer),
    db: Session = Depends(get_db)
):
    """
    Marks every unread notification as read in one call — e.g. a "mark
    all as read" button/action on the Notifications page.
    """
    updated_count = notification_controller.mark_all_notifications_read(db, current_customer.id)
    return NotificationMarkReadResponse(
        message="All notifications marked as read." if updated_count > 0 else "No unread notifications.",
        updated_count=updated_count
    )