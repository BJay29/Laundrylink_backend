from datetime import datetime, timezone
from sqlalchemy import func
from sqlalchemy.orm import Session
from math import radians, cos, sin, asin, sqrt

from app.models import Shop, ServiceType, AddOn, PromoCode, Review
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


def _get_rating_map(db: Session, shop_ids: list[int]) -> dict:
    """
    NEW (Rating after order) — {shop_id: (average_rating, rating_count)}
    para sa mga ibinigay na shop. Isang query lang para sa lahat ng shop
    (hindi isang query kada shop). Ang shop na walang review ay wala sa
    resulta — ang tumatawag ang bahalang magbigay ng default (None, 0).

    Ang average ay naka-round sa isang decimal (hal. 4.3).
    """
    if not shop_ids:
        return {}

    rows = (
        db.query(
            Review.shop_id,
            func.avg(Review.rating),
            func.count(Review.id),
        )
        .filter(Review.shop_id.in_(shop_ids))
        .group_by(Review.shop_id)
        .all()
    )
    return {
        shop_id: (round(float(avg), 1), int(count))
        for shop_id, avg, count in rows
        if avg is not None
    }


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

    UPDATED (Rating after order) — average_rating at rating_count ay
    kino-compute din ng manu-mano (isang grouped query para sa lahat ng
    shop, see _get_rating_map()).
    """
    shops = db.query(Shop).filter(Shop.is_published == True).all()
    rating_map = _get_rating_map(db, [shop.id for shop in shops])

    responses = []
    for shop in shops:
        response = ShopPublicResponse.model_validate(shop)
        response.active_promos = [
            PromoCodePreview.model_validate(p) for p in _get_active_promos(shop)
        ]
        average_rating, rating_count = rating_map.get(shop.id, (None, 0))
        response.average_rating = average_rating
        response.rating_count = rating_count
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

    FIXED (Online Payment toggle bug — Booking & Order Tracking Flow
    Fix): SAME class of bug as is_online above, three more fields this
    time — gcash_qr_url, paymaya_qr_url, qr_code_url ay hindi rin
    dating pinapasa dito (kahit ilang beses na naka-upload ang shop ng
    QR sa Optimization Settings, palaging null ang bumabalik sa Shop
    Detail — kaya BookingFormPage's `_onlinePaymentAvailable` check
    (`qrCodeUrl != null`) ay LAGING false anuman ang gawin ng shop).
    At kahit naitama na ang QR fields, hindi pa rin ito sapat: dagdag
    ding idinagdag ang accepts_cash/accepts_cod/accepts_online — ito
    ang totoong "Payment Methods" toggle mismo (hiwalay sa "may
    na-upload bang QR" na tanong), na dating wala rin dito kahit
    nasa schema na at nasa Shop model na ang column. Kailangan PAREHONG
    naka-ON ang toggle AT may QR bago ituring na available ng mobile
    app ang Online Payment — see Shop.acceptsOnline sa shop.dart at
    _onlinePaymentAvailable sa booking_form_page.dart.

    UPDATED (Rating after order) — average_rating at rating_count ay
    kasama na rin sa manual constructor call sa ibaba.
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

    average_rating, rating_count = _get_rating_map(db, [shop.id]).get(shop.id, (None, 0))

    return ShopDetailResponse(
        id=shop.id,
        shop_name=shop.shop_name,
        address=shop.address,
        latitude=shop.latitude,
        longitude=shop.longitude,
        has_delivery=shop.has_delivery,
        delivery_fee=shop.delivery_fee,
        is_online=shop.is_online,  # FIX: dati'y nawawala, kaya default False palagi
        # FIX (Online Payment toggle bug): dati'y nawawala rin ang tatlong
        # ito, kaya laging null ang QR sa mobile app kahit na-upload na.
        gcash_qr_url=shop.gcash_qr_url,
        paymaya_qr_url=shop.paymaya_qr_url,
        # FIX (root cause — qr_code_url permanently null): ang web app's
        # Optimization Settings page (OptimizationSettings.jsx) ay
        # nagsu-save LANG papunta sa gcash_qr_url / paymaya_qr_url —
        # walang UI na nagse-set ng qr_code_url mismo, kaya laging null
        # ito sa DB anuman ang gawin ng shop sa web. Pero ang mobile
        # app's BookingFormPage ay `qr_code_url` (isang generic QR)
        # LANG ang tinitingnan — kaya hindi kailanman makikita ng
        # mobile app ang QR na na-upload sa web.
        #
        # Fallback na ito sa halip na hintayin munang gawan ng bagong
        # migration + bagong upload slot ang web app: kung wala pang
        # nakatalagang generic qr_code_url, gamitin na lang ang
        # gcash_qr_url — o paymaya_qr_url kung wala ring gcash — bilang
        # ang QR na ipapakita sa Online Payment ng mobile app. Kapag
        # nag-decide kayong palawakin pa ito (hal. hayaang pumili ang
        # customer ng GCash vs PayMaya sa checkout mismo), dito rin
        # babaguhin.
        qr_code_url=shop.qr_code_url or shop.gcash_qr_url or shop.paymaya_qr_url,
        # FIX (Online Payment toggle bug): ito mismo ang toggle na
        # dating hindi dumarating sa mobile app — see docstring sa itaas.
        accepts_cash=shop.accepts_cash,
        accepts_cod=shop.accepts_cod,
        accepts_online=shop.accepts_online,
        average_rating=average_rating,
        rating_count=rating_count,
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

    UPDATED (Rating after order) — same average_rating/rating_count
    treatment as get_all_shops() above.
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
    rating_map = _get_rating_map(db, [shop.id for shop in shops])

    results = []
    for shop in shops:
        distance = _haversine_km(latitude, longitude, shop.latitude, shop.longitude)
        if distance <= radius_km:
            response = ShopPublicResponse.model_validate(shop)
            response.distance_km = distance
            response.active_promos = [
                PromoCodePreview.model_validate(p) for p in _get_active_promos(shop)
            ]
            average_rating, rating_count = rating_map.get(shop.id, (None, 0))
            response.average_rating = average_rating
            response.rating_count = rating_count
            results.append(response)

    results.sort(key=lambda s: s.distance_km)
    return results