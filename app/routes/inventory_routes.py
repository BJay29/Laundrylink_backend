from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.database import get_db
from app.controller import inventory_controller
from app.schemas import InventoryItemCreate, InventoryItemUpdate, InventoryItemResponse

router = APIRouter(prefix="/inventory", tags=["Inventory"])

@router.get("/", response_model=List[InventoryItemResponse])
def read_inventory(shop_id: int, db: Session = Depends(get_db)):
    """Fetches all inventory items for a specific shop."""
    items = inventory_controller.get_inventory(db, shop_id=shop_id)
    return items

@router.post("/", response_model=InventoryItemResponse)
def create_inventory_item(item_data: InventoryItemCreate, db: Session = Depends(get_db)):
    """Adds a new item to the inventory."""
    return inventory_controller.create_item(db, item_data=item_data)

@router.put("/{item_id}", response_model=InventoryItemResponse)
def update_inventory_item(item_id: int, item_data: InventoryItemUpdate, db: Session = Depends(get_db)):
    """Updates stock levels or reorder points for an existing item."""
    updated_item = inventory_controller.update_item(db, item_id=item_id, item_data=item_data)
    if not updated_item:
        raise HTTPException(status_code=404, detail="Item not found")
    return updated_item

@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inventory_item(item_id: int, db: Session = Depends(get_db)):
    """Deletes an item from the inventory."""
    deleted_item = inventory_controller.delete_item(db, item_id=item_id)
    if not deleted_item:
        raise HTTPException(status_code=404, detail="Item not found")
    return None