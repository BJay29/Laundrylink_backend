from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import NotificationResponse, NotificationMarkReadResponse, UnreadCountResponse
from app.controller import notification_controller
from app import models
from app.security import get_current_customer

# Notification router — lahat ng endpoints dito ay para sa CUSTOMER
# (mobile app) na naka-login, kagaya ng /bookings/mine at /bookings/customer.
router = APIRouter(
    prefix="/notifications",
    tags=["Notifications"]
)


@router.get("/mine", response_model=List[NotificationResponse])
def get_my_notifications(
    current_customer: models.Customer = Depends(get_current_customer),  # ⬅️ galing sa customer JWT
    db: Session = Depends(get_db)
):
    """
    Ibinabalik ang LAHAT ng notifications ng naka-login na customer,
    pinaka-bago muna. Ito ang pinagkukunan ng Notification Page —
    gamitin ang `is_read` field ng bawat item para i-render ang
    read/unread na visual state (hal. bold + dot para sa unread,
    normal/greyed-out para sa read na), at ang `type` field para
    pumili ng tamang icon/kulay kada item.
    """
    return notification_controller.get_customer_notifications(db, current_customer.id)


@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    current_customer: models.Customer = Depends(get_current_customer),  # ⬅️ galing sa customer JWT
    db: Session = Depends(get_db)
):
    """
    Bilang lang ng unread notifications ng customer — ito ang tinatawag
    ng bell icon sa top bar (hal. sa app startup at habang naka-open ang
    app) para malaman kung magpapakita ba ng tuldok/number badge sa
    ibabaw ng bell icon, at kung ano ang bilang na ipapakita.
    """
    count = notification_controller.get_unread_count(db, current_customer.id)
    return {"unread_count": count}


@router.patch("/{notification_id}/read", response_model=NotificationMarkReadResponse)
def mark_notification_read(
    notification_id: int,
    current_customer: models.Customer = Depends(get_current_customer),  # ⬅️ galing sa customer JWT
    db: Session = Depends(get_db)
):
    """
    Minamarka ang isang specific notification bilang read — hal. kapag
    tina-tap ng customer ang isang notification item sa listahan (para
    lumipat ito mula "unread" papuntang "read" na visual state, at
    mabawasan ang unread count sa bell badge).
    """
    return notification_controller.mark_read(db, notification_id, current_customer.id)


@router.patch("/mark-all-read", response_model=NotificationMarkReadResponse)
def mark_all_notifications_read(
    current_customer: models.Customer = Depends(get_current_customer),  # ⬅️ galing sa customer JWT
    db: Session = Depends(get_db)
):
    """
    Minamarka LAHAT ng notifications ng customer bilang read nang
    sabay-sabay — hal. kapag binuksan ng customer ang buong
    Notification Page, o may "Mark all as read" button doon.
    """
    return notification_controller.mark_all_read(db, current_customer.id)