from sqlalchemy.orm import Session
from app.models import ActivityLog


def log_activity(db: Session, shop_id: int, actor_name: str, actor_role: str, description: str):
    """
    Reusable helper na tinatawag ng ibang controllers (booking, machine,
    inventory, settings, atbp.) tuwing may mahalagang aksyon na dapat
    ma-record sa Activity Log.

    IMPORTANTE: walang db.commit() dito nang sinasadya — ang entry na
    ito ay dapat maging BAHAGI ng parehong transaction/commit ng caller
    (hal. kasabay ng db.commit() sa create_booking). Kung mag-fail ang
    buong operation (halimbawa kulang ang stock), dapat ma-rollback din
    ang log entry — hindi dapat may "orphan log" na nagsasabing may
    nangyaring aksyon kahit na-fail pala ang buong transaction.

    Gamit:
        from app.controller.activity_controller import log_activity
        ...
        log_activity(db, shop_id, current_user.email, current_user.role,
                     f"Gumawa ng booking para kay {customer_name} - ₱{price}")
        db.commit()  # isang commit lang para sa lahat
    """
    db.add(ActivityLog(
        shop_id=shop_id,
        actor_name=actor_name,
        actor_role=actor_role,
        description=description
    ))


def get_activity_logs(db: Session, shop_id: int, limit: int = 100):
    """
    Retrieves the most recent activity log entries for a shop, newest first.

    limit caps the result size (default 100) to keep the response light —
    this is a simple recent-history view, not a full paginated archive.
    Can be extended later with date_from/date_to or actor filters if needed.
    """
    return (
        db.query(ActivityLog)
        .filter(ActivityLog.shop_id == shop_id)
        .order_by(ActivityLog.timestamp.desc())
        .limit(limit)
        .all()
    )