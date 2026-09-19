import os
import uuid
from typing import Optional

from supabase import create_client, Client

# --- CONFIG ---
# Set these as environment variables on your backend host (Render, etc.):
#   SUPABASE_URL              -> your project's URL (same one the web/
#                                mobile apps use for Auth)
#   SUPABASE_SERVICE_ROLE_KEY -> Project Settings -> API -> service_role
#                                key (NOT the anon key — this key bypasses
#                                Storage RLS, which is fine here because
#                                every route that calls this service has
#                                ALREADY authenticated the caller via
#                                get_current_user()/get_current_customer()
#                                before this module is ever touched).
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

_supabase_client: Optional[Client] = None


def get_supabase_client() -> Client:
    """
    Lazily creates (and caches) a single Supabase client for the life of
    the process. Raises immediately with a clear message if the two
    required env vars are missing, instead of failing later with a
    confusing attribute error deep inside supabase-py.
    """
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must both be set "
                "as environment variables for Storage uploads to work."
            )
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _supabase_client


# --- VALIDATION CONSTANTS (shared by every upload route) ---

ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
}

MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB — plenty for a QR or receipt screenshot


def extension_for_content_type(content_type: str) -> str:
    """Falls back to 'jpg' for any content type not in the allow-list —
    callers should validate against ALLOWED_IMAGE_CONTENT_TYPES BEFORE
    calling this, this is just a safe default so a path always has some
    extension even if validation is ever skipped by mistake."""
    return ALLOWED_IMAGE_CONTENT_TYPES.get(content_type, "jpg")


def build_storage_path(*segments, extension: str) -> str:
    """
    Builds a collision-safe storage path like
    "shop/13/gcash/8f3a2c9d1b7e.png" or
    "booking/482/8f3a2c9d1b7e.jpg" — a short random suffix instead of a
    plain timestamp so two uploads in the same millisecond (unlikely,
    but free to guard against) never collide, and so old file names
    can't be guessed/enumerated by a stranger.
    """
    unique_suffix = uuid.uuid4().hex[:12]
    path_prefix = "/".join(str(segment) for segment in segments)
    return f"{path_prefix}/{unique_suffix}.{extension}"


def upload_image_to_bucket(bucket: str, path: str, file_bytes: bytes, content_type: str) -> str:
    """
    Uploads raw image bytes to the given Supabase Storage bucket at the
    given path, then returns the bucket's public URL for that path.

    `upsert: true` means re-uploading to the exact same path (shouldn't
    normally happen given build_storage_path()'s random suffix, but kept
    as a safety net) replaces the old file instead of erroring.

    Both buckets this function is used with ("payment-qr-codes" and
    "payment-proofs") must already exist and be set Public in the
    Supabase Dashboard — see the Storage setup steps from earlier in
    this project. Since uploads go through this service-role client
    rather than a browser/app's own Supabase session, Storage RLS
    INSERT policies are bypassed entirely for these two routes; the
    real authorization check already happened via get_current_user()/
    get_current_customer() in the FastAPI route before this function
    is ever called.
    """
    client = get_supabase_client()
    client.storage.from_(bucket).upload(
        path=path,
        file=file_bytes,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    return client.storage.from_(bucket).get_public_url(path)


def delete_image_from_bucket(bucket: str, path: str) -> None:
    """
    Optional cleanup helper — e.g. call this when a shop replaces their
    QR code, to avoid leaving orphaned files in Storage forever. Not
    wired up anywhere yet; safe to ignore if you don't need it.
    """
    client = get_supabase_client()
    client.storage.from_(bucket).remove([path])