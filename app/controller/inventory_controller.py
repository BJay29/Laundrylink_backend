from sqlalchemy.orm import Session
from app.models import InventoryItem, InventoryLog
from app.schemas import InventoryItemCreate, InventoryItemUpdate

def get_inventory(db: Session, shop_id: int):
    """Retrieves all inventory items for a specific shop."""
    return db.query(InventoryItem).filter(InventoryItem.shop_id == shop_id).all()

def get_item(db: Session, item_id: int):
    """Retrieves a single inventory item by its ID."""
    return db.query(InventoryItem).filter(InventoryItem.id == item_id).first()

def create_item(db: Session, item_data: InventoryItemCreate):
    """Creates a new inventory item in the database with usage_rate support."""
    new_item = InventoryItem(
        item_name=item_data.item_name,
        category=item_data.category, # Added category support
        current_stock=item_data.current_stock,
        reorder_point=item_data.reorder_point,
        unit=item_data.unit,
        usage_rate=item_data.usage_rate, 
        shop_id=item_data.shop_id
    )
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item

def update_item(db: Session, item_id: int, item_data: InventoryItemUpdate):
    """Updates the stock level, reorder point, and usage_rate of an existing item."""
    db_item = get_item(db, item_id)
    if db_item:
        if item_data.current_stock is not None:
            db_item.current_stock = item_data.current_stock
        if item_data.reorder_point is not None:
            db_item.reorder_point = item_data.reorder_point
        if item_data.usage_rate is not None:
            db_item.usage_rate = item_data.usage_rate
        if item_data.category is not None:
            db_item.category = item_data.category
        
        db.commit()
        db.refresh(db_item)
    return db_item

def record_usage(db: Session, item_id: int, quantity_used: float):
    """
    Deducts stock from an item and creates an InventoryLog record.
    Used for tracking consumption trends for the graph.
    """
    db_item = get_item(db, item_id)
    if db_item and db_item.current_stock >= quantity_used:
        # Deduct the stock
        db_item.current_stock -= quantity_used
        
        # Create log for trend tracking
        new_log = InventoryLog(
            item_id=item_id,
            quantity_used=quantity_used
        )
        db.add(new_log)
        db.commit()
        db.refresh(db_item)
        return db_item
    return None

def delete_item(db: Session, item_id: int):
    """Removes an item from the inventory."""
    db_item = get_item(db, item_id)
    if db_item:
        db.delete(db_item)
        db.commit()
    return db_item