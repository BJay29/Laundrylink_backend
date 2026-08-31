from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.controller import shop_controller
from app.schemas import ShopPublicResponse, ShopDetailResponse

router = APIRouter(prefix="/shops", tags=["Shops (Public)"])


@router.get("/", response_model=list[ShopPublicResponse])
def list_shops(db: Session = Depends(get_db)):
    """
    Buong listahan ng published shops. Ito ang gagamitin ng mobile app
    sa Home carousel at Shop Selection Page — walang auth na kailangan.
    """
    return shop_controller.get_all_shops(db)


@router.get("/nearby", response_model=list[ShopPublicResponse])
def nearby_shops(
    latitude: float = Query(...),
    longitude: float = Query(...),
    radius_km: float = Query(5.0, gt=0),
    db: Session = Depends(get_db),
):
    """
    Shops sa loob ng radius_km mula sa ibinigay na coordinates.
    Babalikan na lang ito pagkatapos ma-set ang lat/long ng shops.
    """
    return shop_controller.get_nearby_shops(db, latitude, longitude, radius_km)


@router.get("/{shop_id}", response_model=ShopDetailResponse)
def shop_detail(shop_id: int, db: Session = Depends(get_db)):
    """Shop Detail page: info + services."""
    shop = shop_controller.get_shop_detail(db, shop_id)
    if not shop:
        raise HTTPException(status_code=404, detail="Shop not found")
    return shop