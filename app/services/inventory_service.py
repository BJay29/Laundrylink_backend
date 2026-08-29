from sqlalchemy.orm import Session
from app.models import InventoryItem, InventoryLog
from datetime import datetime, timedelta
from sqlalchemy import func

def get_predicted_depletion_date(db: Session, item_id: int, shop_id: int):
    """
    Calculates when an item will run out based on consumption history logged in InventoryLog.
    Formula: (Current Stock) / (Average Daily Consumption) = Days Remaining

    FIXED: shop_id is now a required parameter and is filtered on. Before,
    this queried by item_id alone — any caller that knew (or guessed) an
    item_id could get depletion predictions for an item belonging to a
    different shop.
    """
    item = db.query(InventoryItem).filter(
        InventoryItem.id == item_id,
        InventoryItem.shop_id == shop_id
    ).first()

    # Check if item exists (and belongs to this shop) and has stock
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
    Returns a list of items that are LOW or CRITICAL for this shop.

    FIXED: This used to run its own looser classification
    (`current_stock <= reorder_point`, no CRITICAL tier), which was a
    SECOND, DIFFERENT definition of "low stock" from the one used by
    inventory_controller.get_inventory_dashboard_stats(). That meant
    anything calling this function (e.g. low-stock email alerts) could
    disagree with what the Inventory Dashboard shows — e.g. an email
    saying "3 items low" while the dashboard shows a different count or
    severity breakdown.

    Now delegates to inventory_controller.classify_stock_status(), the
    single source of truth for CRITICAL/LOW/OK, so every consumer of
    "low stock" status (dashboard, email alerts, anything else) always
    agrees.
    """
    # Local import to avoid a circular import at module load time
    # (inventory_controller also does a local import of this module).
    from app.controller.inventory_controller import classify_stock_status

    items = db.query(InventoryItem).filter(InventoryItem.shop_id == shop_id).all()

    return [
        item for item in items
        if classify_stock_status(item.current_stock, item.reorder_point) in ("LOW", "CRITICAL")
    ]


def get_inventory_analytics(db: Session, item_id: int, days: int = 7):
    """
    Retrieves usage history for a specific item to power the Inventory Graph.
    Returns a list of usage per day.

    NOTE: No shop_id filter here by design — this is only ever called from
    inventory_controller.get_item_analytics(), which already verifies the
    item belongs to the caller's shop via get_item(item_id, shop_id)
    BEFORE calling this. If you ever call this function directly from a
    new route or script, verify item ownership yourself first.
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