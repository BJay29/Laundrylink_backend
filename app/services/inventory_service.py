from sqlalchemy.orm import Session
from app.models import InventoryItem, Booking
from datetime import datetime, timedelta

def get_predicted_depletion_date(db: Session, item_id: int):
    """
    Calculates when an item will run out based on consumption history.
    Formula: (Current Stock) / (Average Daily Consumption) = Days Remaining
    """
    item = db.query(InventoryItem).filter(InventoryItem.id == item_id).first()
    if not item or item.current_stock <= 0:
        return None

    # Get recent bookings (e.g., last 30 days) to calculate daily usage
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_bookings = db.query(Booking).filter(
        Booking.created_at >= thirty_days_ago
    ).all()

    # Simple logic: assume 1 load consumes a fixed amount (e.g., 0.1kg of detergent)
    # You can adjust the 'consumption_per_load' based on your shop settings
    consumption_per_load = 0.1 
    total_consumed = sum([b.loads for b in recent_bookings]) * consumption_per_load
    daily_usage = total_consumed / 30 

    if daily_usage <= 0:
        return "N/A - No recent usage detected"

    days_remaining = item.current_stock / daily_usage
    depletion_date = datetime.utcnow() + timedelta(days=days_remaining)
    
    return depletion_date.strftime("%Y-%m-%d")

def check_low_stock_alerts(db: Session, shop_id: int):
    """
    Returns a list of items that are below or at the reorder point.
    """
    items = db.query(InventoryItem).filter(InventoryItem.shop_id == shop_id).all()
    alerts = [
        item for item in items 
        if item.current_stock <= item.reorder_point
    ]
    return alerts