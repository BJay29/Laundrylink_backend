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
    """Creates a new inventory item in the database with usage_rate and category support."""
    try:
        # Validate that shop_id exists
        from app.models import Shop
        shop = db.query(Shop).filter(Shop.id == item_data.shop_id).first()
        if not shop:
            print(f"Invalid shop_id: {item_data.shop_id}")
            return None
        
        new_item = InventoryItem(
            item_name=item_data.item_name,
            category=item_data.category,
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
    except Exception as e:
        db.rollback()
        print(f"Database Error in create_item: {str(e)}")
        return None

def update_item(db: Session, item_id: int, item_data: InventoryItemUpdate):
    """Updates the stock level, reorder point, and usage_rate of an existing item."""
    try:
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
    except Exception as e:
        db.rollback()
        print(f"Database Error in update_item: {e}")
        return None

def record_usage(db: Session, item_id: int, quantity_used: float):
    """
    Deducts stock from an item and creates an InventoryLog record.
    Used for tracking consumption trends.
    """
    try:
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
    except Exception as e:
        db.rollback()
        print(f"Database Error in record_usage: {e}")
        return None

def delete_item(db: Session, item_id: int):
    """Removes an item from the inventory."""
    try:
        db_item = get_item(db, item_id)
        if db_item:
            db.delete(db_item)
            db.commit()
            return db_item
        return None
    except Exception as e:
        db.rollback()
        print(f"Database Error in delete_item: {e}")
        return None

def get_item_analytics(db: Session, item_id: int, days: int = 7):
    """
    Retrieves analytics and usage graph data for a specific item.
    Returns item details with consumption history for charting.
    """
    try:
        from app.services.inventory_service import get_inventory_analytics
        
        db_item = get_item(db, item_id)
        if not db_item:
            return None
        
        # Get usage history from service
        usage_history = get_inventory_analytics(db, item_id=item_id, days=days)
        
        return {
            "item_id": db_item.id,
            "item_name": db_item.item_name,
            "unit": db_item.unit,
            "current_stock": db_item.current_stock,
            "reorder_point": db_item.reorder_point,
            "usage_history": usage_history
        }
    except Exception as e:
        print(f"Error in get_item_analytics: {e}")
        return None

def get_inventory_dashboard_stats(db: Session, shop_id: int):
    """
    Retrieves complete inventory dashboard statistics including low stock alerts.
    """
    try:
        from app.services.inventory_service import check_low_stock_alerts
        
        # Get all items for this shop
        all_items = get_inventory(db, shop_id=shop_id)
        
        # Get low stock alerts
        low_stock_items = check_low_stock_alerts(db, shop_id=shop_id)
        
        # Calculate statistics
        total_items = len(all_items)
        items_critical = sum(1 for item in all_items if item.current_stock <= (item.reorder_point * 0.5))
        items_low = sum(1 for item in all_items if item.reorder_point * 0.5 < item.current_stock <= item.reorder_point)
        items_ok = total_items - items_critical - items_low
        
        # Format alerts
        alerts = []
        for item in low_stock_items:
            status = "CRITICAL" if item.current_stock <= (item.reorder_point * 0.5) else "LOW"
            alerts.append({
                "id": item.id,
                "item_name": item.item_name,
                "current_stock": item.current_stock,
                "reorder_point": item.reorder_point,
                "unit": item.unit,
                "status": status
            })
        
        return {
            "total_items": total_items,
            "items_ok": items_ok,
            "items_low": items_low,
            "items_critical": items_critical,
            "total_stock_value": sum(item.current_stock for item in all_items),
            "low_stock_alerts": alerts
        }
    except Exception as e:
        print(f"Error in get_inventory_dashboard_stats: {e}")
        return None