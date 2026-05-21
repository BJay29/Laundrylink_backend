from sqlalchemy.orm import Session
from app.models import InventoryItem
from app.schemas import InventoryItemCreate, InventoryItemUpdate

def get_inventory(db: Session, shop_id: int):
    """Retrieves all inventory items for a specific shop."""
    return db.query(InventoryItem).filter(InventoryItem.shop_id == shop_id).all()

def get_item(db: Session, item_id: int):
    """Retrieves a single inventory item by its ID."""
    return db.query(InventoryItem).filter(InventoryItem.id == item_id).first()

def create_item(db: Session, item_data: InventoryItemCreate):
    """Creates a new inventory item in the database."""
    new_item = InventoryItem(
        item_name=item_data.item_name,
        current_stock=item_data.current_stock,
        reorder_point=item_data.reorder_point,
        unit=item_data.unit,
        shop_id=item_data.shop_id
    )
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item

def update_item(db: Session, item_id: int, item_data: InventoryItemUpdate):
    """Updates the stock level and reorder point of an existing item."""
    db_item = get_item(db, item_id)
    if db_item:
        if item_data.current_stock is not None:
            db_item.current_stock = item_data.current_stock
        if item_data.reorder_point is not None:
            db_item.reorder_point = item_data.reorder_point
        
        db.commit()
        db.refresh(db_item)
    return db_item

def delete_item(db: Session, item_id: int):
    """Removes an item from the inventory."""
    db_item = get_item(db, item_id)
    if db_item:
        db.delete(db_item)
        db.commit()
    return db_item