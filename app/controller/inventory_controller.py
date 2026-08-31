from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models import InventoryItem, InventoryLog, Shop
from app.schemas import InventoryItemCreate, InventoryItemUpdate
from app.controller.activity_controller import log_activity
from app import models

# --- LOW STOCK CLASSIFICATION (SINGLE SOURCE OF TRUTH) ---
CRITICAL_THRESHOLD_RATIO = 0.5  # 50% pababa ng reorder_point = CRITICAL

def classify_stock_status(current_stock: float, reorder_point: float) -> str:
    """
    Tanging pinagmumulan ng CRITICAL / LOW / OK classification sa buong app.
    - CRITICAL: kulang na sa 50% ng reorder point
    - LOW: nasa/mababa sa reorder point pero hindi pa CRITICAL
    - OK: mas mataas sa reorder point
    """
    if reorder_point <= 0:
        return "OK"
    if current_stock <= (reorder_point * CRITICAL_THRESHOLD_RATIO):
        return "CRITICAL"
    if current_stock <= reorder_point:
        return "LOW"
    return "OK"


def get_inventory(db: Session, shop_id: int):
    """
    Retrieves all inventory items for a specific shop.
    NOTE: read-only, no Activity Log entry.
    """
    return db.query(InventoryItem).filter(InventoryItem.shop_id == shop_id).all()


def get_item(db: Session, item_id: int, shop_id: int):
    """
    Retrieves a single inventory item by its ID, SCOPED TO THE SHOP.
    NOTE: read-only, no Activity Log entry. Used internally by mutating
    functions below to first look up the item before logging changes.
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


def create_item(db: Session, item_data: InventoryItemCreate, current_user: models.User):
    """
    Creates a new inventory item in the database with usage_rate and
    category support.

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id, so this action can be attributed to whoever performed it.
    shop_id is still derived from current_user.shop_id, never from the
    client-supplied item_data.shop_id.
    """
    shop_id = current_user.shop_id

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
        db.flush()  # kailangan para makuha ang new_item.item_name bago mag-commit

        # --- ACTIVITY LOG ---
        log_activity(
            db, shop_id,
            actor_name=current_user.email,
            actor_role=current_user.role,
            description=(
                f"Nagdagdag ng bagong inventory item: {new_item.item_name} "
                f"({new_item.current_stock}{new_item.unit})"
            )
        )

        db.commit()
        db.refresh(new_item)
        return new_item
    except Exception as e:
        db.rollback()
        print(f"Database Error in create_item: {str(e)}")
        return None


def update_item(db: Session, item_id: int, item_data: InventoryItemUpdate, current_user: models.User):
    """
    Updates all editable fields of an existing inventory item including item_name.

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id.
    """
    shop_id = current_user.shop_id

    try:
        db_item = get_item(db, item_id, shop_id)
        if db_item:
            changed_fields = []

            if item_data.item_name is not None:
                db_item.item_name = item_data.item_name
                changed_fields.append("item_name")
            if item_data.current_stock is not None:
                db_item.current_stock = item_data.current_stock
                changed_fields.append("current_stock")
            if item_data.reorder_point is not None:
                db_item.reorder_point = item_data.reorder_point
                changed_fields.append("reorder_point")
            if item_data.usage_rate is not None:
                db_item.usage_rate = item_data.usage_rate
                changed_fields.append("usage_rate")
            if item_data.category is not None:
                db_item.category = item_data.category
                changed_fields.append("category")
            if item_data.unit is not None:
                db_item.unit = item_data.unit
                changed_fields.append("unit")

            # --- ACTIVITY LOG ---
            if changed_fields:
                log_activity(
                    db, shop_id,
                    actor_name=current_user.email,
                    actor_role=current_user.role,
                    description=(
                        f"Nag-update ng inventory item: {db_item.item_name} "
                        f"({', '.join(changed_fields)})"
                    )
                )

            db.commit()
            db.refresh(db_item)
        return db_item
    except Exception as e:
        db.rollback()
        print(f"Database Error in update_item: {e}")
        return None


def record_usage(db: Session, item_id: int, quantity_used: float, current_user: models.User):
    """
    Deducts stock from an item and creates an InventoryLog record.
    Used for MANUAL consumption tracking (e.g. staff records usage
    directly from the Inventory page, not tied to a booking).

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id.

    NOTE: hiwalay ito sa validate_and_deduct_stock() sa ibaba — ito ay
    para sa STANDALONE na paggamit (may sariling commit), habang ang
    validate_and_deduct_stock() ay para sa MULTI-ITEM na booking flow
    (walang commit, dahil isang malaking transaction lang ang gagawin
    sa booking_controller para sa lahat ng items nang sabay-sabay, at
    doon na rin naka-log ang buong booking action — hindi dapat doble
    ang log kada item).
    """
    shop_id = current_user.shop_id

    try:
        db_item = get_item(db, item_id, shop_id)
        if db_item and db_item.current_stock >= quantity_used:
            db_item.current_stock -= quantity_used

            new_log = InventoryLog(
                item_id=item_id,
                quantity_used=quantity_used
            )
            db.add(new_log)

            # --- ACTIVITY LOG ---
            log_activity(
                db, shop_id,
                actor_name=current_user.email,
                actor_role=current_user.role,
                description=(
                    f"Nag-record ng manual usage para sa {db_item.item_name}: "
                    f"-{quantity_used}{db_item.unit}"
                )
            )

            db.commit()
            db.refresh(db_item)
            return db_item
        return None
    except Exception as e:
        db.rollback()
        print(f"Database Error in record_usage: {e}")
        return None


def delete_item(db: Session, item_id: int, current_user: models.User):
    """
    Removes an item from the inventory.

    UPDATED (Activity Log): now takes current_user instead of a bare
    shop_id.
    """
    shop_id = current_user.shop_id

    try:
        db_item = get_item(db, item_id, shop_id)
        if db_item:
            item_name = db_item.item_name
            db.delete(db_item)

            # --- ACTIVITY LOG ---
            log_activity(
                db, shop_id,
                actor_name=current_user.email,
                actor_role=current_user.role,
                description=f"Nag-tanggal ng inventory item: {item_name}"
            )

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
    NOTE: read-only, no Activity Log entry.
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
    NOTE: read-only, no Activity Log entry.
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


def validate_and_deduct_stock(db: Session, item_id: int, quantity: float, shop_id: int) -> InventoryItem:
    """
    Reusable helper na tinatawag ng booking_controller sa loob ng loop,
    isang beses kada item sa multi-item na booking (hal. detergent +
    fabric conditioner sa iisang booking).

    NOTE: walang Activity Log entry dito nang sinasadya — ang buong
    booking action (kasama na ang lahat ng inventory items na ginamit)
    ay isang beses na naka-log sa booking_controller.create_booking(),
    para hindi dumoble ang log entries kada item sa loob ng isang booking.

    NOTE: walang db.commit() dito rin — ang caller (create_booking sa
    booking_controller) ang bahalang mag-commit ng BUONG transaction
    nang sabay-sabay.
    """
    item = get_item(db, item_id, shop_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Inventory item ID {item_id} not found for this shop."
        )
    if item.current_stock < quantity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient stock for '{item.item_name}'. Available: {item.current_stock}{item.unit}, needed: {quantity}{item.unit}."
        )

    item.current_stock -= quantity
    db.add(InventoryLog(item_id=item.id, quantity_used=quantity))
    return item