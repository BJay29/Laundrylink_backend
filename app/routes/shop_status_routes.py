from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.controller import shop_status_controller
from app.database import get_db
from app.schemas import ShopStatusResponse, ShopStatusUpdate
from app.security import get_current_user

# Shop status — manual "Accepting bookings" toggle, operating hours, at
# terminal heartbeat. Para sa web dashboard (staff) lang; nakukuha ng
# mobile ang effective status (is_open / closed_reason) sa mga shop
# endpoint na.
router = APIRouter(prefix="/shop-status", tags=["Shop Status"])


@router.get("/", response_model=ShopStatusResponse)
def get_shop_status(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return shop_status_controller.get_status(db, current_user)


@router.post("/heartbeat", response_model=ShopStatusResponse)
def shop_heartbeat(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ipinapadala ng web bawat ~60s habang bukas ang dashboard."""
    return shop_status_controller.heartbeat(db, current_user)


@router.patch("/", response_model=ShopStatusResponse)
def update_shop_status(
    update_data: ShopStatusUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return shop_status_controller.update_status(db, current_user, update_data)