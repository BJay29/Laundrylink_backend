from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import models
from app.controller.activity_controller import log_activity
from app.schemas import ShopStatusUpdate
from app.services.shop_status import compute_shop_status, parse_hhmm


def _get_shop(db: Session, shop_id: int) -> models.Shop:
    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not shop:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found.")
    return shop


def _status_dict(shop: models.Shop) -> dict:
    st = compute_shop_status(shop)
    return {
        "accepting_bookings": True if shop.accepting_bookings is None else bool(shop.accepting_bookings),
        "opening_time": shop.opening_time,
        "closing_time": shop.closing_time,
        "is_open": st.is_open,
        "closed_reason": st.message,
        "reason_code": st.reason_code,
        "terminal_connected": st.terminal_connected,
        "within_hours": st.within_hours,
        "last_seen_at": shop.last_seen_at,
    }


def get_status(db: Session, current_user: models.User) -> dict:
    return _status_dict(_get_shop(db, current_user.shop_id))


def heartbeat(db: Session, current_user: models.User) -> dict:
    """
    Ipinapadala ng web dashboard bawat ~60 segundo habang bukas ito.
    Ina-update lang ang last_seen_at (hindi nagla-log ng activity).
    """
    shop = _get_shop(db, current_user.shop_id)
    shop.last_seen_at = datetime.now(timezone.utc)
    try:
        db.commit()
        db.refresh(shop)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Heartbeat Error: {str(e)}"
        )
    return _status_dict(shop)


def update_status(db: Session, current_user: models.User, data: ShopStatusUpdate) -> dict:
    shop = _get_shop(db, current_user.shop_id)
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No changes were provided.")

    notes = []

    if "accepting_bookings" in changes and changes["accepting_bookings"] is not None:
        shop.accepting_bookings = changes["accepting_bookings"]
        notes.append("accepting bookings" if shop.accepting_bookings else "paused new bookings")

    if "opening_time" in changes or "closing_time" in changes:
        new_open = changes.get("opening_time", shop.opening_time)
        new_close = changes.get("closing_time", shop.closing_time)
        if bool(new_open) != bool(new_close):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Set both opening and closing time, or clear both."
            )
        if new_open and parse_hhmm(new_open) == parse_hhmm(new_close):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Opening and closing time can't be the same."
            )
        shop.opening_time = new_open or None
        shop.closing_time = new_close or None
        notes.append(
            f"operating hours {new_open}–{new_close}" if new_open else "removed operating hours"
        )

    try:
        log_activity(
            db, shop.id,
            actor_name=current_user.full_name or current_user.email,
            actor_role=current_user.role,
            description="Shop status updated: " + ", ".join(notes)
        )
        db.commit()
        db.refresh(shop)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Shop Status Error: {str(e)}"
        )
    return _status_dict(shop)


def reset_stale_online_flags(db: Session) -> None:
    """
    Opsyonal — tawagin minsan sa startup ng server (main.py) para hindi
    maiwang "online" ang shop na na-stuck ang flag noong nag-crash/
    nag-redeploy ang server. Walang epekto sa heartbeat.
    """
    db.query(models.Shop).update({models.Shop.is_online: False})
    db.commit()