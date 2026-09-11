from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import models, schemas


def update_customer_profile(
    db: Session,
    current_customer: models.Customer,
    update_data: schemas.CustomerUpdate,
) -> models.Customer:
    """
    Nag-a-apply ng partial update sa "Personal information" (full_name,
    mobile_number) ng CURRENTLY LOGGED-IN customer lang. Email at
    password ay SINASADYANG hindi kasama dito — email hindi pa
    pinapayagang baguhin, at password change ay direktang Supabase Auth
    SDK na ang bahala (client-side updateUser call), hindi na dumadaan
    dito.

    model_dump(exclude_unset=True) ginamit para tunay na PARTIAL update
    lang — kung hindi ipinasa ng client ang isang field, hindi natin
    ito gagalawin (hindi babaguhin papuntang None/default), gaya ng
    dating ginagawa ng dating PATCH endpoint.
    """
    updates = update_data.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided to update.",
        )

    for field, value in updates.items():
        setattr(current_customer, field, value)

    db.add(current_customer)
    db.commit()
    db.refresh(current_customer)

    return current_customer


# REMOVED: register_customer() at authenticate_customer() — hindi na
# FastAPI ang humahawak nito, Supabase Auth SDK na (see comment sa
# customer_auth_routes.py). Password change ay hindi rin na kasama
# dito — Supabase Auth SDK direkta (client-side updateUser call).