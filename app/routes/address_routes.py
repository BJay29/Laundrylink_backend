from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from typing import List
from app.database import get_db
from app.schemas import AddressCreate, AddressUpdate, AddressResponse
from app.controller import address_controller
from app import models
from app.security import get_current_customer

# Address router — lahat ng endpoints dito ay naka-scope sa naka-login
# na CUSTOMER (mobile app), kagaya ng /bookings/mine at /notifications/mine.
router = APIRouter(
    prefix="/addresses",
    tags=["Addresses"]
)


@router.get("/mine", response_model=List[AddressResponse])
def get_my_addresses(
    current_customer: models.Customer = Depends(get_current_customer),  # ⬅️ galing sa customer JWT
    db: Session = Depends(get_db)
):
    """
    Ibinabalik ang lahat ng saved addresses ng naka-login na customer —
    default muna, tapos pinaka-bago sa mga natitira. Ito ang datos sa
    likod ng "Saved addresses" section sa Profile page.
    """
    return address_controller.get_customer_addresses(db, current_customer.id)


@router.post("/", response_model=AddressResponse, status_code=status.HTTP_201_CREATED)
def create_address(
    address_data: AddressCreate,
    current_customer: models.Customer = Depends(get_current_customer),  # ⬅️ galing sa customer JWT
    db: Session = Depends(get_db)
):
    """
    Nagdadagdag ng bagong saved address para sa naka-login na customer.
    Awtomatikong nagiging default ang unang address na gagawin.
    """
    return address_controller.create_address(db, current_customer.id, address_data)


@router.patch("/{address_id}", response_model=AddressResponse)
def update_address(
    address_id: int,
    address_data: AddressUpdate,
    current_customer: models.Customer = Depends(get_current_customer),  # ⬅️ galing sa customer JWT
    db: Session = Depends(get_db)
):
    """
    Nag-e-edit ng isang existing address (label, address text, pin,
    o kung ito na ang gagawing default) — 404 kung wala o hindi pag-aari
    ng naka-login na customer.
    """
    return address_controller.update_address(db, address_id, current_customer.id, address_data)


@router.delete("/{address_id}")
def delete_address(
    address_id: int,
    current_customer: models.Customer = Depends(get_current_customer),  # ⬅️ galing sa customer JWT
    db: Session = Depends(get_db)
):
    """
    Nagtatanggal ng isang saved address. Kung ang tinanggal ay ang
    default, awtomatikong ginagawang default ang susunod na pinaka-
    bagong address (kung meron pa).
    """
    return address_controller.delete_address(db, address_id, current_customer.id)