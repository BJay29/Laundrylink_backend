from sqlalchemy.orm import Session
from math import radians, cos, sin, asin, sqrt

from app.models import Shop, ServiceType
from app.schemas import ShopPublicResponse, ShopDetailResponse, ShopServicePreview


def _haversine_km(lat1, lon1, lat2, lon2):
    """Distance sa pagitan ng dalawang GPS coordinates, in kilometers."""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return round(6371 * c, 2)  # 6371 = Earth radius sa km


def get_all_shops(db: Session):
    """
    Buong listahan ng published shops — ginagamit sa Shop Selection Page
    at Home carousel. Walang location filtering, kaya gumagana ito kahit
    NULL pa ang latitude/longitude ng mga shops.
    """
    shops = db.query(Shop).filter(Shop.is_published == True).all()
    return [ShopPublicResponse.model_validate(s) for s in shops]


def get_shop_detail(db: Session, shop_id: int):
    """Shop Detail page: shop info + services."""
    shop = (
        db.query(Shop)
        .filter(Shop.id == shop_id, Shop.is_published == True)
        .first()
    )
    if not shop:
        return None

    services = (
        db.query(ServiceType)
        .filter(ServiceType.shop_id == shop_id, ServiceType.is_active == True)
        .all()
    )

    return ShopDetailResponse(
        id=shop.id,
        shop_name=shop.shop_name,
        address=shop.address,
        latitude=shop.latitude,
        longitude=shop.longitude,
        services=[ShopServicePreview.model_validate(s) for s in services],
    )


def get_nearby_shops(db: Session, latitude: float, longitude: float, radius_km: float = 5.0):
    """
    Naive approach muna: kunin lahat ng published shops na may coordinates,
    i-filter/i-sort sa Python gamit ang haversine. Sapat na ito sa scale
    ngayon (7 shops); kapag dumami na, pwede nang PostGIS/bounding-box query.

    NOTE: hindi pa ito magagamit habang NULL pa ang latitude/longitude ng
    mga shops — babalikan na lang ito pagkatapos ma-set ang coordinates.
    """
    shops = (
        db.query(Shop)
        .filter(
            Shop.is_published == True,
            Shop.latitude.isnot(None),
            Shop.longitude.isnot(None),
        )
        .all()
    )

    results = []
    for shop in shops:
        distance = _haversine_km(latitude, longitude, shop.latitude, shop.longitude)
        if distance <= radius_km:
            response = ShopPublicResponse.model_validate(shop)
            response.distance_km = distance
            results.append(response)

    results.sort(key=lambda s: s.distance_km)
    return results