from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.controller import review_controller

# Parehong customer dependency na ginagamit sa address_routes.py at
# notification_routes.py (naka-login na CUSTOMER mula sa Supabase JWT).
from app.security import get_current_customer, get_current_shop_id

router = APIRouter(
    prefix="/reviews",
    tags=["Reviews"]
)


@router.post("/", response_model=schemas.ReviewResponse, status_code=status.HTTP_201_CREATED)
def submit_review(
    data: schemas.ReviewCreate,
    customer: models.Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """
    Customer (mobile app) — mag-rate ng isang booking pagkatapos itong
    maging "Claimed".

    Body:
        {
            "booking_id": 123,
            "rating": 5,                  # 1 hanggang 5
            "comment": "Ang bilis!"       # opsyonal, hanggang 300 characters
        }

    Mga posibleng error:
        404 — wala ang booking, o hindi sa iyo.
        400 — hindi pa "Claimed" ang booking.
        409 — nakapag-rate ka na sa booking na ito.
        422 — di-wasto ang rating (hindi 1 hanggang 5) o masyadong
              mahaba ang komento.
    """
    return review_controller.create_review(db, customer, data)


@router.get("/shop", response_model=schemas.ShopReviewsResponse)
def get_my_shop_reviews(
    limit: int = Query(100, ge=1, le=500),
    shop_id: int = Depends(get_current_shop_id),
    db: Session = Depends(get_db),
):
    """
    Owner/staff (web) — mga rating at komento ng SARILING shop ng
    naka-login (shop_id galing sa JWT, gaya ng ibang /analytics
    endpoints). Ibinabalik ang buod (average, bilang, bilang ng bawat
    bituin) at ang pinakabagong `limit` na reviews. Unang pangalan lang
    ng customer ang kasama.
    """
    return review_controller.get_shop_reviews(db, shop_id, limit)