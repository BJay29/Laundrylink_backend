import hmac
import os

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.controller import webhook_controller
from app.schemas import SupabaseWebhookPayload

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# Shared secret na ilalagay natin sa Supabase webhook's custom header
# (X-Webhook-Secret) — see Supabase Dashboard → Integrations →
# Database Webhooks setup. Pinakamahalagang security layer ito: kung
# wala nito, kahit sino na nakaalam ng URL mo ay makaka-fake ng
# "verified user" payload papunta sa DB mo.
WEBHOOK_SECRET = os.environ["SUPABASE_WEBHOOK_SECRET"]


def verify_webhook_secret(x_webhook_secret: str = Header(...)) -> None:
    """
    Dependency na nag-che-check ng shared secret header bago pa man
    ma-parse ang body. hmac.compare_digest ginamit (sa halip na
    plain == ) para maiwasan ang timing attacks.
    """
    if not hmac.compare_digest(x_webhook_secret, WEBHOOK_SECRET):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret.",
        )


@router.post(
    "/supabase-auth",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_webhook_secret)],
)
async def handle_supabase_auth_webhook(
    payload: SupabaseWebhookPayload,
    db: Session = Depends(get_db),
):
    """
    Tinatanggap ang UPDATE event mula sa Supabase's auth.users table.

    BAKIT UPDATE, HINDI INSERT: ang row sa auth.users ay ginagawa na
    (INSERT) agad-agad pagka-sign-up, BAGO pa man ma-verify ng user
    ang OTP niya. Ang email verification (OTP confirmation) ay
    nag-UUUPDATE lang ng email_confirmed_at column sa parehong row
    (mula null papuntang timestamp). Kaya UPDATE event ang tamang
    trigger para sa "user is now verified", hindi INSERT — kung INSERT
    lang ang paniningnan, ma-sync sa Aiven DB kahit hindi pa verified
    ang user.
    """
    # Interesado lang tayo sa auth.users table, sa "auth" schema, at
    # sa UPDATE event lang — i-ignore ang lahat ng iba pang trigger na
    # baka aksidenteng ma-configure sa hinaharap.
    if payload.table != "users" or payload.schema_name != "auth":
        return {"status": "ignored", "reason": "not an auth.users event"}

    if payload.type != "UPDATE":
        return {"status": "ignored", "reason": "not an UPDATE event"}

    record = payload.record
    if record.email_confirmed_at is None:
        # Hindi pa verified — huwag munang i-sync (hal. UPDATE event na
        # dulot ng ibang column change, hindi ng OTP confirmation).
        return {"status": "ignored", "reason": "email not yet confirmed"}

    # Dapat ipasa ng frontend ang "role" sa signUp() metadata
    # (options.data.role sa Flutter/React) — kung wala, i-default sa
    # "customer" bilang safest assumption.
    metadata = record.raw_user_meta_data or {}
    role = metadata.get("role", "customer")

    result = webhook_controller.sync_verified_user(
        db=db,
        supabase_uid=str(record.id),
        email=record.email,
        role=role,
        metadata=metadata,
    )

    return {"status": "synced", **result}