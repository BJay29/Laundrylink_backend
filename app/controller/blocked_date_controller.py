"""
BLOCKED DATES ("Fully Booked") CONTROLLER

Ang shop mismo (owner/staff) ang nagmamarka ng mga petsang fully booked
na. Hindi na makakapili ang customer sa mobile ng mga petsang iyon, at
tinatanggihan din ng backend ang booking/edit sa petsang iyon (para
hindi ito malusutan ng lumang app o ng ibang kliyente).

NOTE (timezone): ang mga petsa ay "kalendaryong petsa" sa oras ng
Pilipinas (Asia/Manila, UTC+8). Ang pickup_datetime/dropoff_datetime
ng booking ay naka-save bilang UTC, kaya kino-convert muna sa Manila
bago ikumpara — kung hindi, ang 11:00 PM ng Nov 3 sa Manila (15:00 UTC)
ay tama pa rin, pero ang 7:00 AM ng Nov 4 sa Manila (23:00 UTC ng Nov 3)
ay mapagkakamalang Nov 3.
"""
from datetime import datetime, date, timezone, timedelta
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.schemas import BlockedDateCreate
from app.controller.activity_controller import log_activity

MANILA_TZ = timezone(timedelta(hours=8))


def manila_today() -> date:
    """Ang petsa ngayon sa Pilipinas."""
    return datetime.now(MANILA_TZ).date()


def to_manila_date(value) -> Optional[date]:
    """
    Kino-convert ang datetime (aware o naive) sa kalendaryong petsa sa
    Manila. Ang naive datetime ay itinuturing na UTC (parehong
    pagtrato ng buong backend sa mga timestamp). Ang `None` ay
    nagbabalik ng `None`.
    """
    if value is None:
        return None
    # Mahalaga: datetime ang subclass ng date, kaya ito ang unang i-check.
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(MANILA_TZ).date()
    if isinstance(value, date):
        return value
    return None


def list_blocked_dates(db: Session, shop_id: int) -> List[models.BlockedDate]:
    """
    Mga petsang fully booked na UPCOMING pa (ngayon o mas huli, sa
    oras ng Manila), pinakamalapit muna.
    """
    return (
        db.query(models.BlockedDate)
        .filter(
            models.BlockedDate.shop_id == shop_id,
            models.BlockedDate.blocked_date >= manila_today(),
        )
        .order_by(models.BlockedDate.blocked_date.asc())
        .all()
    )


def get_public_blocked_dates(db: Session, shop_id: int) -> List[models.BlockedDate]:
    """Para sa customer (mobile app): mga petsang fully booked ng isang shop."""
    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not shop or not shop.is_published:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop not found."
        )
    return list_blocked_dates(db, shop_id)


def add_blocked_date(db: Session, current_user: models.User, data: BlockedDateCreate) -> models.BlockedDate:
    shop_id = current_user.shop_id
    if shop_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not linked to a shop."
        )

    if data.blocked_date < manila_today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can't mark a past date as fully booked."
        )

    existing = (
        db.query(models.BlockedDate)
        .filter(
            models.BlockedDate.shop_id == shop_id,
            models.BlockedDate.blocked_date == data.blocked_date,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That date is already marked as fully booked."
        )

    actor_name = current_user.full_name or current_user.email

    entry = models.BlockedDate(
        shop_id=shop_id,
        blocked_date=data.blocked_date,
        reason=data.reason,
        created_by=actor_name,
    )

    try:
        db.add(entry)
        log_activity(
            db, shop_id,
            actor_name=actor_name,
            actor_role=current_user.role,
            description=(
                f"Marked {data.blocked_date.strftime('%b %d, %Y')} as fully booked"
                + (f" ({data.reason})" if data.reason else "")
            )
        )
        db.commit()
        db.refresh(entry)
        return entry
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That date is already marked as fully booked."
        )
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error saving fully booked date: {str(e)}"
        )


def remove_blocked_date(db: Session, current_user: models.User, blocked_id: int) -> dict:
    shop_id = current_user.shop_id

    entry = (
        db.query(models.BlockedDate)
        .filter(
            models.BlockedDate.id == blocked_id,
            models.BlockedDate.shop_id == shop_id,
        )
        .first()
    )
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fully booked date not found."
        )

    label = entry.blocked_date.strftime("%b %d, %Y")

    try:
        db.delete(entry)
        log_activity(
            db, shop_id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description=f"Reopened {label} for bookings (removed fully booked mark)"
        )
        db.commit()
        return {"message": f"{label} is open for bookings again."}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error removing fully booked date: {str(e)}"
        )


def assert_date_not_blocked(db: Session, shop_id: int, value) -> None:
    """
    Ginagamit ng booking_controller (create at edit ng customer
    booking). Kapag ang petsa ng pickup/drop-off ay fully booked, mag-
    ra-raise ng 400 na may malinaw na mensahe. Kapag walang petsa
    (None — optional ang drop-off date), walang susuriin.
    """
    day = to_manila_date(value)
    if day is None:
        return

    blocked = (
        db.query(models.BlockedDate)
        .filter(
            models.BlockedDate.shop_id == shop_id,
            models.BlockedDate.blocked_date == day,
        )
        .first()
    )
    if blocked:
        reason = f" ({blocked.reason})" if blocked.reason else ""
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"The shop is fully booked on {day.strftime('%b %d, %Y')}{reason}. "
                "Please choose another date."
            )
        )