from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app import schemas, models
from app.controller import customer_auth_controller
from app.security import get_current_customer

router = APIRouter(
    prefix="/customer",
    tags=["Customer Authentication"]
)


# --- SESSION DATA FETCHING (PROTECTED, SELF ONLY) ---
@router.get("/profile", response_model=schemas.CustomerResponse)
def get_my_customer_profile(current_customer: models.Customer = Depends(get_current_customer)):
    """
    Retrieves session details of the CURRENTLY LOGGED-IN customer only,
    based on the Supabase JWT sent in the Authorization header.
    """
    return current_customer


# NEW — "Personal information" edit form sa mobile app. Partial update
# lang (full_name at/o mobile_number) — email at password sinasadyang
# hindi kasama (see customer_auth_controller.update_customer_profile
# docstring). Protected, self-only — walang customer_id sa path/body,
# kinukuha lang mula sa naka-verify na Supabase JWT.
@router.patch("/profile", response_model=schemas.CustomerResponse)
def update_my_customer_profile(
    update_data: schemas.CustomerUpdate,
    current_customer: models.Customer = Depends(get_current_customer),
    db: Session = Depends(get_db),
):
    return customer_auth_controller.update_customer_profile(db, current_customer, update_data)


# REMOVED (Supabase Auth migration):
#
# POST /customer/register, POST /customer/login — Supabase Auth SDK na
# (signUp / signInWithPassword) sa Flutter mismo ang bahala nito.
#
# PUT /customer/password — password change ay Supabase Auth SDK na rin
# (client-side supabase.auth.updateUser({password: newPassword})),
# hindi na dumadaan sa FastAPI backend.