from sqlalchemy.orm import Session
from app.models import InventoryItem, InventoryLog, Shop
from app.schemas import InventoryItemCreate, InventoryItemUpdate

# --- LOW STOCK CLASSIFICATION (SINGLE SOURCE OF TRUTH) ---
# NOTE: Dating doble ang logic na ito — meron sa get_inventory_dashboard_stats()
# DITO, at meron din malamang sa inventory_service.check_low_stock_alerts().
# Ngayon, ISANG function na lang ang nagde-decide ng status, at parehong
# lugar ay dapat gumamit ng function na ito para laging tugma ang resulta.
CRITICAL_THRESHOLD_RATIO = 0.5  # 50% pababa ng reorder_point = CRITICAL

def classify_stock_status(current_stock: float, reorder_point: float) -> str:
    """
    Tanging pinagmumulan ng CRITICAL / LOW / OK classification sa buong app.
    - CRITICAL: kulang na sa 50% ng reorder point
    - LOW: nasa/mababa sa reorder point pero hindi pa CRITICAL
    - OK: mas mataas sa reorder point
    """
    if reorder_point <= 0:
        return "OK"  # walang defined threshold, iwasan ang division/logic errors
    if current_stock <= (reorder_point * CRITICAL_THRESHOLD_RATIO):
        return "CRITICAL"
    if current_stock <= reorder_point:
        return "LOW"
    return "OK"


def get_inventory(db: Session, shop_id: int):
    """Retrieves all inventory items for a specific shop."""
    return db.query(InventoryItem).filter(InventoryItem.shop_id == shop_id).all()


def get_item(db: Session, item_id: int, shop_id: int):
    """
    Retrieves a single inventory item by its ID, SCOPED TO THE SHOP.

    FIXED: dating walang shop_id filter dito kahit saan — kaya kahit
    anong item_id (kahit sa ibang shop), makikita/mae-edit/made-delete.
    Ngayon, kung hindi kabilang sa shop na ito ang item, wala itong
    ibabalik (None), parang hindi umiiral.
    """
    return db.query(InventoryItem).filter(
        InventoryItem.id == item_id,
        InventoryItem.shop_id == shop_id
    ).first()


def get_inventory_grouped_by_category(db: Session, shop_id: int):
    """Returns inventory organized by category for dropdown UI support."""
    items = get_inventory(db, shop_id=shop_id)
    grouped = {}
    for item in items:
        category = item.category or "General"
        grouped.setdefault(category, []).append(item)
    return grouped


def create_item(db: Session, item_data: InventoryItemCreate, shop_id: int):
    """
    Creates a new inventory item in the database with usage_rate and
    category support.

    FIXED: shop_id ay parameter na ngayon (galing sa JWT via routes),
    HINDI na kinukuha mula sa item_data.shop_id na ipinasa ng client.
    Kahit magpasa pa ang client ng ibang shop_id sa request body,
    ang shop_id ng NAKA-LOGIN na user ang laging gagamitin.
    """
    try:
        shop = db.query(Shop).filter(Shop.id == shop_id).first()
        if not shop:
            print(f"Invalid shop_id: {shop_id}")
            return None

        new_item = InventoryItem(
            item_name=item_data.item_name,
            category=item_data.category,
            current_stock=item_data.current_stock,
            reorder_point=item_data.reorder_point,
            unit=item_data.unit,
            usage_rate=item_data.usage_rate,
            shop_id=shop_id
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)
        return new_item
    except Exception as e:
        db.rollback()
        print(f"Database Error in create_item: {str(e)}")
        return None


def update_item(db: Session, item_id: int, item_data: InventoryItemUpdate, shop_id: int):
    """
    Updates all editable fields of an existing inventory item including item_name.

    FIXED: shop_id filtering added via get_item(). Dating walang
    proteksyon dito — kahit item ng ibang shop, pwedeng i-edit.
    """
    try:
        db_item = get_item(db, item_id, shop_id)
        if db_item:
            if item_data.item_name is not None:
                db_item.item_name = item_data.item_name
            if item_data.current_stock is not None:
                db_item.current_stock = item_data.current_stock
            if item_data.reorder_point is not None:
                db_item.reorder_point = item_data.reorder_point
            if item_data.usage_rate is not None:
                db_item.usage_rate = item_data.usage_rate
            if item_data.category is not None:
                db_item.category = item_data.category
            if item_data.unit is not None:
                db_item.unit = item_data.unit

            db.commit()
            db.refresh(db_item)
        return db_item
    except Exception as e:
        db.rollback()
        print(f"Database Error in update_item: {e}")
        return None


def record_usage(db: Session, item_id: int, quantity_used: float, shop_id: int):
    """
    Deducts stock from an item and creates an InventoryLog record.
    Used for tracking consumption trends.

    FIXED: shop_id filtering added via get_item(). Dating pwedeng
    ibawas ang stock ng ITEM NG IBANG SHOP kung alam lang ang item_id.
    """
    try:
        db_item = get_item(db, item_id, shop_id)
        if db_item and db_item.current_stock >= quantity_used:
            db_item.current_stock -= quantity_used

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


def delete_item(db: Session, item_id: int, shop_id: int):
    """
    Removes an item from the inventory.

    FIXED: shop_id filtering added via get_item(). Dating pwedeng
    matanggal ang item ng IBANG SHOP kung alam lang ang item_id.
    """
    try:
        db_item = get_item(db, item_id, shop_id)
        if db_item:
            db.delete(db_item)
            db.commit()
            return db_item
        return None
    except Exception as e:
        db.rollback()
        print(f"Database Error in delete_item: {e}")
        return None


def get_item_analytics(db: Session, item_id: int, shop_id: int, days: int = 7):
    """
    Retrieves analytics and usage graph data for a specific inventory item.
    Returns item details with consumption history for charting.

    FIXED: shop_id filtering added — dating pwedeng makita ang usage
    history ng item ng IBANG SHOP kung alam lang ang item_id.
    """
    try:
        from app.services.inventory_service import get_inventory_analytics

        db_item = get_item(db, item_id, shop_id)
        if not db_item:
            return None

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

    FIXED: ginagamit na ang iisang classify_stock_status() helper para sa
    lahat ng classification — hindi na duplicated/independent logic dito
    kumpara sa saanman na tumatawag ng check_low_stock_alerts().
    """
    try:
        all_items = get_inventory(db, shop_id=shop_id)

        total_items = len(all_items)
        items_critical = 0
        items_low = 0
        alerts = []

        for item in all_items:
            item_status = classify_stock_status(item.current_stock, item.reorder_point)

            if item_status == "CRITICAL":
                items_critical += 1
                alerts.append({
                    "id": item.id,
                    "item_name": item.item_name,
                    "current_stock": item.current_stock,
                    "reorder_point": item.reorder_point,
                    "unit": item.unit,
                    "status": item_status
                })
            elif item_status == "LOW":
                items_low += 1
                alerts.append({
                    "id": item.id,
                    "item_name": item.item_name,
                    "current_stock": item.current_stock,
                    "reorder_point": item.reorder_point,
                    "unit": item.unit,
                    "status": item_status
                })

        items_ok = total_items - items_critical - items_low

        # Pinaka-mahalaga ang CRITICAL items — ilagay muna sa taas ng listahan
        alerts.sort(key=lambda a: 0 if a["status"] == "CRITICAL" else 1)

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