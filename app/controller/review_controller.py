from fastapi import HTTPException, status
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