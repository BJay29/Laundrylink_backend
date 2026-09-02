from sqlalchemy.orm import Session
from math import radians, cos, sin, asin, sqrt

from app.models import Shop, ServiceType, AddOn
from app.schemas import ShopPublicResponse, ShopDetailResponse, ShopServicePreview, AddOnPreview


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

    NOTE: has_delivery/delivery_fee/is_online ay automatic nang kasama
    dito — model_validate() ay kinukuha lahat ng matching attribute
    names mula sa Shop object, kaya walang extra code na kailangan para
    dito.
    """
    shops = db.query(Shop).filter(Shop.is_published == True).all()
    return [ShopPublicResponse.model_validate(s) for s in shops]


def get_shop_detail(db: Session, shop_id: int):
    """
    Shop Detail page: shop info + services + add-ons.

    UPDATED: dagdag na ang add_ons list (kagaya ng services), at
    explicit na inilagay ang has_delivery/delivery_fee/is_online dahil
    ito ay manual na constructor call (ShopDetailResponse(...)), hindi
    model_validate() na diretso mula sa Shop object.

    FIXED: nakaligtaan dating ilagay ang is_online sa manual constructor
    call sa ibaba, kaya laging False (Closed) ang bumabalik sa Shop
    Detail page kahit True na ang totoong Shop.is_online sa DB. Dahil
    dito, "Open" ang shop sa Home carousel / Shop Selection (gumagamit
    ng model_validate(), na awtomatikong kumukuha ng lahat ng fields),
    pero "Closed" pagpasok sa Shop Detail — same shop, magkaibang
    endpoint construction lang ang dahilan, hindi real status change.
    """
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

    add_ons = (
        db.query(AddOn)
        .filter(AddOn.shop_id == shop_id, AddOn.is_active == True)
        .all()
    )

    return ShopDetailResponse(
        id=shop.id,
        shop_name=shop.shop_name,
        address=shop.address,
        latitude=shop.latitude,
        longitude=shop.longitude,
        has_delivery=shop.has_delivery,
        delivery_fee=shop.delivery_fee,
        is_online=shop.is_online,  # FIX: dati'y nawawala, kaya default False palagi
        services=[ShopServicePreview.model_validate(s) for s in services],
        add_ons=[AddOnPreview.model_validate(a) for a in add_ons],
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