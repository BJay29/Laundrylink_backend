from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app import schemas, database
from app.controller import shop_controller 

router = APIRouter(
    prefix="/shops", 
    tags=["Shops"]
)

# --- UPDATE SHOP INFORMATION ---
@router.put("/update/{shop_id}", response_model=schemas.ShopUpdate)
def update_shop(
    shop_id: int, 
    updated_data: schemas.ShopUpdate, 
    db: Session = Depends(database.get_db)
):
    """
    Endpoint to update laundry shop details like name or address.
    Accessible by the Shop Owner via the Web Dashboard.
    """
    shop = shop_controller.update_shop_info(db=db, shop_id=shop_id, shop_data=updated_data)
    
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
        
    return shop

# --- GET SHOP DETAILS ---
@router.get("/{shop_id}", response_model=schemas.ShopUpdate)
def get_shop_details(
    shop_id: int, 
    db: Session = Depends(database.get_db)
):
    """
    Endpoint to fetch current shop information.
    Used to pre-fill the update form in the Dashboard.
    """
    shop = shop_controller.get_shop_by_id(db=db, shop_id=shop_id)
    return shop