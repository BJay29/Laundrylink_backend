from app.models import Address
from app.schemas import AddressCreate, AddressUpdate
from fastapi import HTTPException, status
from sqlalchemy.orm import Session


def get_customer_addresses(db: Session, customer_id: int):
    """
    Ibinabalik ang lahat ng saved addresses ng customer — default
    (kung meron) muna, tapos pinaka-bago sa mga natitira.
    """
    return (
        db.query(Address)
        .filter(Address.customer_id == customer_id)
        .order_by(Address.is_default.desc(), Address.created_at.desc())
        .all()
    )


def create_address(db: Session, customer_id: int, data: AddressCreate):
    """
    Gumagawa ng bagong saved address.

    Isa lang dapat ang "default" address sa anumang oras kada customer
    — pinapatupad ito dito (hindi DB constraint) sa pamamagitan ng
    pag-uncheck muna ng is_default sa LAHAT ng existing address ng
    customer na ito bago i-save ang bago, kapag:
      (a) sinabi mismo ng customer na is_default=True ang bagong ito, o
      (b) ito ang UNA nilang address (walang pa silang existing) —
          awtomatikong ginagawang default ang unang address para
          hindi na kailangang mag-set pa ng default nang manu-mano.
    """
    existing_count = db.query(Address).filter(Address.customer_id == customer_id).count()
    make_default = data.is_default or existing_count == 0

    try:
        if make_default:
            db.query(Address).filter(Address.customer_id == customer_id).update({"is_default": False})

        address = Address(
            customer_id=customer_id,
            label=data.label,
            address_line=data.address_line,
            latitude=data.latitude,
            longitude=data.longitude,
            is_default=make_default,
        )
        db.add(address)
        db.commit()
        db.refresh(address)
        return address
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error saving address: {str(e)}"
        )


def update_address(db: Session, address_id: int, customer_id: int, data: AddressUpdate):
    """
    Nag-e-edit ng existing address. Naka-scope sa customer_id (hindi
    lang address_id) para hindi ma-edit ng isang customer ang address
    ng ibang tao sa pamamagitan lang ng pag-guess ng ID.

    Kung is_default=True ang ipinasa, tinatanggal muna ang is_default
    flag sa LAHAT ng IBANG address ng customer na ito (hindi kasama
    ang isa itong ine-edit) bago i-apply ang update — para isa lang
    pa rin ang default sa huli.
    """
    address = (
        db.query(Address)
        .filter(Address.id == address_id, Address.customer_id == customer_id)
        .first()
    )
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found."
        )

    update_data = data.model_dump(exclude_unset=True)

    try:
        if update_data.get("is_default") is True:
            db.query(Address).filter(
                Address.customer_id == customer_id,
                Address.id != address_id
            ).update({"is_default": False})

        for field, value in update_data.items():
            setattr(address, field, value)

        db.commit()
        db.refresh(address)
        return address
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating address: {str(e)}"
        )


def delete_address(db: Session, address_id: int, customer_id: int):
    """
    Nagtatanggal ng isang saved address. Kung ang tinanggal ay ang
    dating default, ginagawa na lang na bagong default ang pinaka-
    huling ginawang address sa mga natitira (kung meron pa) — para
    hindi mabitin ang customer nang walang default address kahit may
    natitira pa siyang iba.
    """
    address = (
        db.query(Address)
        .filter(Address.id == address_id, Address.customer_id == customer_id)
        .first()
    )
    if not address:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Address not found."
        )

    was_default = address.is_default

    try:
        db.delete(address)
        db.flush()

        if was_default:
            next_address = (
                db.query(Address)
                .filter(Address.customer_id == customer_id)
                .order_by(Address.created_at.desc())
                .first()
            )
            if next_address:
                next_address.is_default = True

        db.commit()
        return {"message": "Address deleted successfully.", "address_id": address_id}
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting address: {str(e)}"
        )