from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app import schemas, models
from app.controller import activity_controller
from app.security import get_current_user

router = APIRouter(
    prefix="/activity-logs",
    tags=["Activity Logs"]
)


@router.get("/", response_model=List[schemas.ActivityLogResponse])
def list_activity_logs(
    limit: int = Query(100, ge=1, le=500),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lists the most recent activity log entries for the logged-in user's
    own shop, newest first.

    UPDATED: now open to ALL roles (Owner, Manager, Staff) — previously
    restricted to Owner/Manager only via require_role("owner", "manager").
    Visibility is now handled inside get_activity_logs() based on role:
      - Owner/Manager see every entry for the shop.
      - Staff see only entries where they were the actor.

    shop_id is derived from the JWT, not a query param — a user can
    never view another shop's activity log by editing the URL.
    """
    return activity_controller.get_activity_logs(
        db, current_user.shop_id, current_user, limit=limit
    )