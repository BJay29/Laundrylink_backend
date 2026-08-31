from sqlalchemy.orm import Session
from app.models import ActivityLog


def log_activity(db: Session, shop_id: int, actor_name: str, actor_role: str, description: str):
    """
    Reusable helper called by other controllers (booking, machine,
    inventory, settings, etc.) whenever a notable action needs to be
    recorded in the Activity Log.

    IMPORTANT: no db.commit() here on purpose — this entry must be part
    of the SAME transaction/commit as the caller (e.g. alongside
    db.commit() in create_booking). If the overall operation fails
    (e.g. insufficient stock), the log entry should roll back too —
    there should never be an "orphan log" claiming an action happened
    when the transaction actually failed.

    Usage:
        from app.controller.activity_controller import log_activity
        ...
        log_activity(db, shop_id, actor_name, current_user.role,
                     f"Created a booking for {customer_name} - ₱{price}")
        db.commit()  # single commit for everything
    """
    db.add(ActivityLog(
        shop_id=shop_id,
        actor_name=actor_name,
        actor_role=actor_role,
        description=description
    ))


def get_activity_logs(db: Session, shop_id: int, current_user, limit: int = 100):
    """
    Retrieves the most recent activity log entries for a shop, newest first.

    UPDATED: now takes current_user (not just shop_id) so it can apply
    role-based visibility:
      - Owner/Manager: see ALL entries for the shop.
      - Staff: see ONLY entries they personally created (filtered by
        actor_name matching their own full_name/email). Staff are now
        allowed to view the Activity Log page at all (previously
        Owner/Manager-only), but only their own history — this keeps
        the page useful for self-review without exposing what other
        staff members did.

    limit caps the result size (default 100) to keep the response light —
    this is a simple recent-history view, not a full paginated archive.
    """
    query = db.query(ActivityLog).filter(ActivityLog.shop_id == shop_id)

    if current_user.role == "staff":
        actor_identifier = current_user.full_name or current_user.email
        query = query.filter(ActivityLog.actor_name == actor_identifier)

    return (
        query
        .order_by(ActivityLog.timestamp.desc())
        .limit(limit)
        .all()
    )