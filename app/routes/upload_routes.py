from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..security import get_current_user, get_current_customer
from ..services.supabase_storage import (
    upload_image_to_bucket,
    build_storage_path,
    extension_for_content_type,
    ALLOWED_IMAGE_CONTENT_TYPES,
    MAX_FILE_SIZE_BYTES,
)

# Upload router — the ONLY place in the backend that talks to Supabase
# Storage. Every route here requires the caller to already be
# authenticated (as a shop User or a mobile Customer), so the actual
# authorization check happens via get_current_user()/get_current_customer()
# below, before supabase_storage.py's service-role client ever runs.
router = APIRouter(
    prefix="/uploads",
    tags=["Uploads"]
)


async def _read_and_validate_image(file: UploadFile) -> bytes:
    """
    Shared validation for every upload route below: rejects anything
    that isn't PNG/JPG/WEBP, and rejects anything over 5MB. Raises
    HTTPException directly so routes can just `await` this and continue.
    """
    if file.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PNG, JPG, or WEBP images are allowed."
        )

    contents = await file.read()

    if len(contents) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Image must be 5MB or smaller."
        )

    if len(contents) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty."
        )

    return contents


# =========================================================
# SHOP-SIDE UPLOAD (Owner/Staff) — Payment QR codes
# =========================================================

@router.post("/payment-qr", response_model=schemas.UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_payment_qr(
    provider: str = Form(..., description="'gcash' or 'paymaya'"),
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Uploads a shop's GCash or PayMaya QR code image to the
    "payment-qr-codes" Supabase Storage bucket and returns its public
    URL. The caller (Optimization Settings on the web app) is
    responsible for then saving that URL onto the Shop record via
    PUT /settings/profile ({ gcash_qr_url: <url> } or
    { paymaya_qr_url: <url> }) — this endpoint only handles the file
    itself, same separation of concerns as the existing
    apiService.uploadPaymentQR() + apiService.updateShopProfile() pair
    on the frontend.

    Scoped to current_user.shop_id — a staff/owner can only ever upload
    a QR for their own shop, never anyone else's.
    """
    if provider not in ("gcash", "paymaya"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="provider must be 'gcash' or 'paymaya'."
        )

    if not current_user.shop_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Your account isn't linked to a shop yet."
        )

    contents = await _read_and_validate_image(file)
    extension = extension_for_content_type(file.content_type)
    path = build_storage_path("shop", current_user.shop_id, provider, extension=extension)

    public_url = upload_image_to_bucket(
        bucket="payment-qr-codes",
        path=path,
        file_bytes=contents,
        content_type=file.content_type,
    )

    return schemas.UploadResponse(url=public_url)


# =========================================================
# CUSTOMER-SIDE UPLOAD (Mobile App) — Proof of Payment
# =========================================================

@router.post("/payment-proof", response_model=schemas.UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_payment_proof(
    booking_id: int = Form(...),
    file: UploadFile = File(...),
    current_customer: models.Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    """
    Uploads a customer's proof-of-payment screenshot to the
    "payment-proofs" Supabase Storage bucket and returns its public
    URL. This is the endpoint the mobile app's Module C payment screen
    calls (via the [Submit Payment Verification] button) BEFORE
    attaching that URL to the booking itself — see the accompanying
    PATCH /bookings/{id}/submit-payment-proof endpoint in
    booking_routes.py, which is the one that actually flips
    payment_status to "pending_verification".

    Scoped to Booking.customer_id == current_customer.id — a customer
    can only ever upload proof for their OWN booking, never someone
    else's, even if they guess a valid booking_id.
    """
    booking = (
        db.query(models.Booking)
        .filter(
            models.Booking.id == booking_id,
            models.Booking.customer_id == current_customer.id,
        )
        .first()
    )
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found."
        )

    contents = await _read_and_validate_image(file)
    extension = extension_for_content_type(file.content_type)
    path = build_storage_path("booking", booking_id, extension=extension)

    public_url = upload_image_to_bucket(
        bucket="payment-proofs",
        path=path,
        file_bytes=contents,
        content_type=file.content_type,
    )

    return schemas.UploadResponse(url=public_url)