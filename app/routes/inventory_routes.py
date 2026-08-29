from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Dict

from app.database import get_db
from app.controller import inventory_controller
from app.schemas import (
    InventoryItemCreate,
    InventoryItemUpdate,
    InventoryItemResponse,
    InventoryAnalyticsResponse,
    InventoryDashboardStats
)
from app import models
from app.security import get_current_user  # ⬅️ BAGONG IMPORT

router = APIRouter(prefix="/inventory", tags=["Inventory"])


@router.get("/", response_model=List[InventoryItemResponse])
def read_inventory(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Fetches all inventory items for the logged-in user's own shop."""
    try:
        return inventory_controller.get_inventory(db, shop_id=current_user.shop_id)
    except Exception as e:
        print(f"Error fetching inventory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories", response_model=Dict[str, List[InventoryItemResponse]])
def read_inventory_by_category(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Fetches inventory items grouped by category for category/item dropdowns."""
    try:
        return inventory_controller.get_inventory_grouped_by_category(db, shop_id=current_user.shop_id)
    except Exception as e:
        print(f"Error fetching inventory by category: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/alerts", response_model=InventoryDashboardStats)
def get_low_stock_alerts(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieves inventory status dashboard with low stock alerts and inventory
    statistics for the logged-in user's own shop.

    NOTE: dating "/inventory/shop/{shop_id}/alerts" na open sa URL editing —
    ngayon "/inventory/alerts" na lang, walang path param, base sa JWT.
    """
    try:
        stats = inventory_controller.get_inventory_dashboard_stats(db, shop_id=current_user.shop_id)
        return stats
    except Exception as e:
        print(f"Error fetching inventory stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=InventoryItemResponse)
def create_inventory_item(
    item_data: InventoryItemCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Adds a new item to the logged-in user's own shop inventory.
    item_data.shop_id (if present in the body) is ignored — shop_id
    always comes from the JWT.
    """
    try:
        if not item_data.item_name or not item_data.item_name.strip():
            raise HTTPException(status_code=400, detail="Item name is required")

        result = inventory_controller.create_item(db, item_data=item_data, shop_id=current_user.shop_id)

        if not result:
            raise HTTPException(
                status_code=400,
                detail="Failed to create item - please check all required fields are filled correctly"
            )

        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"CRITICAL ERROR in create_inventory_item: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Database error: {str(e)}"
        )


@router.post("/{item_id}/use", response_model=InventoryItemResponse)
def record_item_usage(
    item_id: int,
    quantity: float,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Manually records consumption of an item belonging to the logged-in
    user's own shop.
    """
    updated_item = inventory_controller.record_usage(
        db, item_id=item_id, quantity_used=quantity, shop_id=current_user.shop_id
    )
    if not updated_item:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Insufficient stock, item not found, or item does not belong to your shop"
        )
    return updated_item


@router.put("/{item_id}", response_model=InventoryItemResponse)
def update_inventory_item(
    item_id: int,
    item_data: InventoryItemUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Updates an existing inventory item belonging to the logged-in user's own shop."""
    updated_item = inventory_controller.update_item(
        db, item_id=item_id, item_data=item_data, shop_id=current_user.shop_id
    )
    if not updated_item:
        raise HTTPException(status_code=404, detail="Item not found")
    return updated_item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inventory_item(
    item_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Deletes an item from the logged-in user's own shop inventory."""
    deleted_item = inventory_controller.delete_item(db, item_id=item_id, shop_id=current_user.shop_id)
    if not deleted_item:
        raise HTTPException(status_code=404, detail="Item not found")
    return None


@router.get("/{item_id}/analytics", response_model=InventoryAnalyticsResponse)
def get_item_analytics(
    item_id: int,
    days: int = Query(7, ge=1, le=90),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieves usage analytics and graph data for a specific inventory item
    belonging to the logged-in user's own shop.
    """
    try:
        analytics = inventory_controller.get_item_analytics(
            db, item_id=item_id, shop_id=current_user.shop_id, days=days
        )
        if not analytics:
            raise HTTPException(status_code=404, detail="Item not found or no usage data available")
        return analytics
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error fetching analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))