from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas


# Ang status ng booking na dapat bago payagang mag-rate (tapos na at
# kinuha na ng customer ang laundry).
RATABLE_STATUS = "claimed"


def create_review(db: Session, customer: models.Customer, data: schemas.ReviewCreate) -> models.Review:
    """
    NEW (Rating after order) — nagse-save ng rating ng customer sa isang
    booking.

    Mga tseke (sa ganitong pagkakasunod):
      1. Dapat umiiral ang booking AT sa customer na ito. Kapag hindi
         niya booking, 404 din ang ibabalik (hindi 403), para hindi
         malaman ng ibang customer kung may booking na may ganoong id.
      2. Dapat "Claimed" na ang booking — hindi pwedeng mag-rate habang
         ginagawa pa ang laundry.
      3. Dapat hindi pa nakapag-rate ang booking (isang rating lang
         kada booking; hindi na mababago pagkatapos ma-submit).

    Ang database mismo ay may UNIQUE constraint sa reviews.booking_id,
    kaya kahit sabay ang dalawang request (double-tap sa mobile), isa
    lang ang papasok — ang pangalawa ay mahuhuli ng IntegrityError sa
    ibaba at gagawing malinaw na 409 na error.

    Ang shop_id ay kinokopya mula sa booking (hindi mula sa request),
    para hindi mapeke ng customer kung kaninong shop ang nire-rate.
    """
    booking = (
        db.query(models.Booking)
        .filter(models.Booking.id == data.booking_id)
        .first()
    )
    if not booking or booking.customer_id != customer.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found."
        )

    if (booking.status or "").strip().lower() != RATABLE_STATUS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You can only rate an order after it has been claimed."
        )

    if booking.review is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already rated this order."
        )

    review = models.Review(
        booking_id=booking.id,
        customer_id=customer.id,
        shop_id=booking.shop_id,
        rating=data.rating,
        comment=data.comment,
    )
    db.add(review)
    try:
        db.commit()
    except IntegrityError:
        # Sabay na pangalawang submit — natalo sa UNIQUE(booking_id).
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already rated this order."
        )
    db.refresh(review)
    return review


def get_shop_reviews(db: Session, shop_id: int, limit: int = 100) -> dict:
    """
    NEW (Rating after order — web) — para sa Reviews page at Dashboard
    card ng owner/staff. Naka-scope sa shop_id na galing sa JWT ng
    naka-login (hindi tinatanggap mula sa request), kaya hindi
    makikita ang reviews ng ibang shop.

    Ibinabalik:
      - summary: average, kabuuang bilang, at bilang ng bawat bituin
        (kinukuwenta sa LAHAT ng reviews ng shop, hindi lang sa `limit`)
      - reviews: pinakabago muna, hanggang `limit`

    Privacy: unang pangalan lang ng customer ang isinasama.
    """
    average, count = (
        db.query(func.avg(models.Review.rating), func.count(models.Review.id))
        .filter(models.Review.shop_id == shop_id)
        .one()
    )

    distribution = {str(star): 0 for star in range(5, 0, -1)}
    for rating, rating_count in (
        db.query(models.Review.rating, func.count(models.Review.id))
        .filter(models.Review.shop_id == shop_id)
        .group_by(models.Review.rating)
        .all()
    ):
        distribution[str(rating)] = int(rating_count)

    rows = (
        db.query(models.Review, models.Customer.full_name, models.Booking.service_type)
        .join(models.Booking, models.Review.booking_id == models.Booking.id)
        .outerjoin(models.Customer, models.Review.customer_id == models.Customer.id)
        .filter(models.Review.shop_id == shop_id)
        .order_by(models.Review.created_at.desc())
        .limit(limit)
        .all()
    )

    reviews = []
    for review, full_name, service_type in rows:
        first_name = (full_name or "").strip().split(" ")[0] or None
        reviews.append({
            "id": review.id,
            "booking_id": review.booking_id,
            "rating": review.rating,
            "comment": review.comment,
            "customer_first_name": first_name,
            "service_type": service_type,
            "created_at": review.created_at,
        })

    return {
        "summary": {
            "average_rating": round(float(average), 1) if average is not None else None,
            "rating_count": int(count or 0),
            "distribution": distribution,
        },
        "reviews": reviews,
    }