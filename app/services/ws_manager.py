from typing import Dict, List
from fastapi import WebSocket
from app.database import SessionLocal
from app import models

# NEW — well-known broadcast event type constants ("type" field of the
# dict passed to manager.broadcast()), so callers across the codebase
# (booking_controller.py) don't hardcode magic strings scattered in
# several places. Add new event types here as the system grows.
EVENT_NEW_BOOKING_REQUEST = "new_booking_request"
EVENT_BOOKING_CANCELLED_BY_CUSTOMER = "booking_cancelled_by_customer"
# NEW (Weighing / Finalize Pricing feature) — fired by
# booking_controller.finalize_booking_pricing() after staff finalizes
# the actual weight/price of a mobile booking. This is SHOP-scoped only
# (see ConnectionManager docstring below) — it refreshes the Service
# Terminal's own "Awaiting Weighing" panel in real time. It does NOT by
# itself notify the customer's mobile app; that side of the
# notification uses the Notification table (notification_controller.
# create_notification()), since this ConnectionManager only tracks
# Service Terminal connections, not individual customer devices/sessions.
# A true customer-side push (WebSocket or FCM) would need a separate
# customer-scoped channel, which does not exist yet in this codebase.
EVENT_BOOKING_PRICE_FINALIZED = "booking_price_finalized"


class ConnectionManager:
    """
    Nagtatrack ng mga aktibong WebSocket connections, naka-grupo per
    shop_id. Isang shop ay pwedeng magkaroon ng maraming naka-open na
    Service Terminal tabs/devices nang sabay-sabay (hal. dalawang staff,
    magkaibang computer) — kaya listahan ng connections bawat shop_id,
    hindi iisa lang.

    UPDATED: Ang connection presence na ito ang ginagamit na ngayong
    "online" signal ng shop — kapag may kahit isang naka-connect na
    Service Terminal, itinuturing na "online" ang shop (Shop.is_online =
    True); kapag naubos na ang lahat ng connections, "offline" (False).
    Ginagamit ito ng mobile app para i-disable ang "Book Now" kung walang
    tumatanggap ng booking sa kasalukuyan.

    NOTE (Weighing / Finalize Pricing feature — reconciliation): ang
    klase na ito ay eksklusibong SHOP-scoped — bawat entry sa
    active_connections ay isang SHOP (maraming Service Terminal devices
    ng shop na iyon), HINDI indibidwal na customer. Kaya ang
    EVENT_BOOKING_PRICE_FINALIZED na broadcast (see finalize_
    booking_pricing() sa booking_controller.py) ay dumarating lang sa
    Service Terminal, hindi sa mobile app ng customer. Para sa
    "totoong" real-time push papunta sa customer (gaya ng inilarawan sa
    orihinal na Admin Dashboard spec bilang FCM/WebSocket listener),
    kailangan ng bagong, hiwalay na customer-scoped connection registry
    — wala pa nito ang codebase na ito. Sa ngayon, ang customer-facing
    "real-time"-ish update ay sa pamamagitan ng Notification table
    (notification_controller.create_notification()), na pino-poll ng
    mobile app sa GET /notifications at GET /bookings/mine.

    Gumagamit ng SessionLocal() direkta (hindi Depends(get_db)) dahil
    walang request-scoped dependency injection sa loob ng WebSocket
    connection lifecycle — kailangang gawa/isara mismo ang sariling
    session dito.
    """

    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, shop_id: int):
        await websocket.accept()

        # Bago idagdag: alamin muna kung ITO ang UNANG connection para sa
        # shop na ito — kung oo, ito ang magiging trigger para i-mark
        # ang shop bilang "online".
        is_first_connection = shop_id not in self.active_connections or not self.active_connections[shop_id]

        self.active_connections.setdefault(shop_id, []).append(websocket)

        if is_first_connection:
            self._set_shop_online_status(shop_id, is_online=True)

    def disconnect(self, websocket: WebSocket, shop_id: int):
        connections = self.active_connections.get(shop_id)
        if connections and websocket in connections:
            connections.remove(websocket)

        if connections is not None and not connections:
            self.active_connections.pop(shop_id, None)
            # Huling connection ng shop na ito ang naalis — walang
            # matitirang naka-bukas na Service Terminal, kaya "offline" na.
            self._set_shop_online_status(shop_id, is_online=False)

    async def broadcast(self, shop_id: int, message: dict):
        """
        Ipinapadala ang message sa LAHAT ng naka-connect na Service
        Terminal instance ng shop na ito. Kung walang naka-connect
        (walang bukas na Service Terminal tab), tahimik lang itong
        walang epekto — hindi error, dahil GET /bookings/awaiting-approval,
        GET /bookings/awaiting-weighing, atbp. pa rin ang sisiguradong
        makikita ang booking sa susunod na page load/refresh.

        `message["type"]` ay dapat isa sa EVENT_* constants sa itaas
        (o katumbas na string) — see doon para sa listahan ng kasalukuyang
        event types at kung sino ang dapat makinig sa bawat isa.
        """
        connections = self.active_connections.get(shop_id, [])
        dead_connections = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)
        for dead in dead_connections:
            self.disconnect(dead, shop_id)

    def _set_shop_online_status(self, shop_id: int, is_online: bool):
        """
        Bagong helper — nag-a-update ng Shop.is_online sa database.
        Ginawang synchronous (hindi async) at may sariling DB session
        dahil ito ay isang "side effect" lang ng connection tracking,
        hindi bahagi ng request/response cycle ng ibang endpoints.

        Nasa loob ng try/except/finally para masigurong lagi itong
        nagsasara ng session, kahit magka-error sa DB update — hindi
        dapat ma-crash ang buong WebSocket connect/disconnect flow kung
        magkaroon ng isyu ang DB update na ito.
        """
        db = SessionLocal()
        try:
            shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
            if shop and shop.is_online != is_online:
                shop.is_online = is_online
                db.commit()
        except Exception as e:
            print(f"Failed to update shop.is_online for shop_id={shop_id}: {e}")
            db.rollback()
        finally:
            db.close()


manager = ConnectionManager()