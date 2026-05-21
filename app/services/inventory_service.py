from sqlalchemy.orm import Session
from app.models import InventoryItem, InventoryLog
from datetime import datetime, timedelta
from sqlalchemy import func

def get_predicted_depletion_date(db: Session, item_id: int):
    """
    Calculates when an item will run out based on consumption history logged in InventoryLog.
    Formula: (Current Stock) / (Average Daily Consumption) = Days Remaining
    """
    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    
    # Check if item exists and has stock
    if not item or item.current_stock <= 0:
        return None

    # Get logs from the last 30 days to calculate accurate daily usage
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    recent_usage = db.query(func.sum(InventoryLog.quantity_used)).filter(
        InventoryLog.item_id == item_id,
        InventoryLog.timestamp >= thirty_days_ago
    ).scalar() or 0.0

    # Calculate daily average usage
    daily_usage = recent_usage / 30 

    if daily_usage <= 0:
        return "N/A - No recent usage detected"

    # Days remaining calculation
    days_remaining = item.current_stock / daily_usage
    depletion_date = datetime.utcnow() + timedelta(days=days_remaining)
    
    return depletion_date.strftime("%Y-%m-%d")

def check_low_stock_alerts(db: Session, shop_id: int):
    """
    Returns a list of items that are below or at the reorder point.
    """
    return db.query(InventoryItem).filter(
        InventoryItem.shop_id == shop_id,
        InventoryItem.current_stock <= InventoryItem.reorder_point
    ).all()

def get_inventory_analytics(db: Session, item_id: int, days: int = 7):
    """
    Retrieves usage history for a specific item to power the Inventory Graph.
    Returns a list of usage per day.
    """
    start_date = datetime.utcnow() - timedelta(days=days)
    
    # Aggregates usage grouped by date
    history = db.query(
        func.date(InventoryLog.timestamp).label("date"),
        func.sum(InventoryLog.quantity_used).label("total_used")
    ).filter(
        InventoryLog.item_id == item_id,
        InventoryLog.timestamp >= start_date
    ).group_by(func.date(InventoryLog.timestamp)).all()
    
    return [{"date": h.date.strftime("%Y-%m-%d"), "usage": h.total_used} for h in history]