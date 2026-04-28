from sqlalchemy.orm import Session
from app import models, schemas
from fastapi import HTTPException

def update_shop_info(db: Session, shop_id: int, shop_data: schemas.ShopUpdate):
    """
    Updates laundry shop details. 
    Uses partial updates so it won't overwrite existing data with nulls.
    """
    # 1. Search for the shop in the database
    db_shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    
    if not db_shop:
        raise HTTPException(status_code=404, detail="Shop not found")

    # 2. Convert Pydantic model to a dictionary
    # exclude_unset=True ensures only provided fields are updated
    update_values = shop_data.model_dump(exclude_unset=True)
    
    # 3. Apply changes dynamically to the database object
    for key, value in update_values.items():
        if hasattr(db_shop, key):
            setattr(db_shop, key, value)

    # 4. Commit and refresh to get the updated state
    db.commit()
    db.refresh(db_shop)
    
    return db_shop

def get_shop_by_id(db: Session, shop_id: int):
    """
    Retrieves full shop details using its primary key.
    Useful for displaying shop info on the Owner Dashboard.
    """
    db_shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    
    if not db_shop:
        raise HTTPException(status_code=404, detail="Shop not found")
        
    return db_shop