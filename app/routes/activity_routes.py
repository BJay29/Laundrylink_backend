from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app import schemas, models
from app.controller import activity_controller
from app.security import get_current_user, require_role

router = APIRouter(
    prefix="/activity-logs",
    tags=["Activity Logs"]
)


@router.get("/", response_model=List[schemas.ActivityLogResponse])
def list_activity_logs(
    limit: int = Query(100, ge=1, le=500),
    current_user: models.User = Depends(require_role("owner", "manager")),
    db: Session = Depends(get_db)
):
    """
    Lists the most recent activity log entries for the logged-in user's
    own shop, newest first.

    Restricted to Owner and Manager roles only (per the earlier decision
    that Staff should not see the Activity Log) — enforced via
    require_role("owner", "manager"), so a Staff-role JWT gets a 403
    even with a technically valid token.

    shop_id is derived from the JWT, not a query param — a user can
    never view another shop's activity log by editing the URL.
    """
    return activity_controller.get_activity_logs(db, current_user.shop_id, limit=limit)