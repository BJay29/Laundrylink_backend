from datetime import datetime, timezone
from sqlalchemy.orm import Session
from math import radians, cos, sin, asin, sqrt

from app.models import Shop, ServiceType, AddOn, PromoCode
from app.schemas import (
    ShopPublicResponse, ShopDetailResponse, ShopServicePreview, AddOnPreview,
    PromoCodePreview,
)


def _haversine_km(lat1, lon1, lat2, lon2):
    """Distance sa pagitan ng dalawang GPS coordinates, in kilometers."""
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return round(6371 * c, 2)  # 6371 = Earth radius sa km


def _get_active_promos(shop: Shop) -> list[PromoCode]:
    """
    NEW (Home page promo carousel) — filters a shop's promo_codes down
    to the ones that are actually usable RIGHT NOW: is_active, not
    past its expires_at, and not past max_uses. Mirrors the same three
    checks _apply_promo_code() in booking_controller.py enforces at
    checkout time — a promo shown here that a customer then tries to
    type in should always still be valid, never a stale advertisement
    for something that already expired between page-load and checkout.

    Iterates shop.promo_codes (already available via the relationship)
    rather than issuing a fresh query — shop counts are small enough
    (see get_nearby_shops() note below) that this stays cheap, and it
    keeps this helper usable for both a single shop and a full list
    without needing a session passed in.
    """
    now = datetime.now(timezone.utc)
    active = []
    for promo in shop.promo_codes:
        if not promo.is_active:
            continue
        if promo.expires_at and promo.expires_at < now:
            continue
        if promo.max_uses is not None and promo.times_used >= promo.max_uses:
            continue
        active.append(promo)
    return active


def get_all_shops(db: Session):
    """
    Buong listahan ng published shops — ginagamit sa Shop Selection Page
    at Home carousel. Walang location filtering, kaya gumagana ito kahit
    NULL pa ang latitude/longitude ng mga shops.

    NOTE: has_delivery/delivery_fee/is_online ay automatic nang kasama
    dito — model_validate() ay kinukuha lahat ng matching attribute
    names mula sa Shop object, kaya walang extra code na kailangan para
    dito.

    UPDATED (Home page promo carousel) — active_promos ay hindi kasama
    sa model_validate() (walang katumbas na attribute sa Shop mismo),
    kaya kino-compute at itina-set ito ng manu-mano pagkatapos, gamit
    ang _get_active_promos() sa itaas. Ang mobile app's Home page ang
    bahalang mag-filter (client-side) kung aling shops ang mayroong
    active_promos na hindi blangko para ipakita sa promo carousel.
    """
    shops = db.query(Shop).filter(Shop.is_published == True).all()
    responses = []
    for shop in shops:
        response = ShopPublicResponse.model_validate(shop)
        response.active_promos = [
            PromoCodePreview.model_validate(p) for p in _get_active_promos(shop)
        ]
        responses.append(response)
    return responses


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

    UPDATED (Home page promo carousel) — same active_promos treatment
    as get_all_shops() above, kept consistent so a shop's promo badge
    doesn't disappear just because the customer's device has location
    on and this endpoint gets hit instead of the plain listing.
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
            response.active_promos = [
                PromoCodePreview.model_validate(p) for p in _get_active_promos(shop)
            ]
            results.append(response)

    results.sort(key=lambda s: s.distance_km)
    return results