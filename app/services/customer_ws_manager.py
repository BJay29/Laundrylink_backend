from typing import Dict, List
from fastapi import WebSocket

# Well-known broadcast event type constant, kapatid ng
# EVENT_NEW_BOOKING_REQUEST/EVENT_BOOKING_CANCELLED_BY_CUSTOMER/
# EVENT_BOOKING_PRICE_FINALIZED sa ws_manager.py (shop side). Ito ang
# customer-side na katumbas — ito ang "type" field na ipinapadala sa
# customer_manager.send_to_customer() calls sa booking_controller.py
# (update_booking_status(), mark_booking_as_paid(), reject_payment(),
# finalize_booking_pricing(), submit_payment_proof()).
EVENT_BOOKING_UPDATED = "booking_updated"


class CustomerConnectionManager:
    """
    Nagtatrack ng mga aktibong WebSocket connections, naka-grupo per
    customer_id — kapatid ng ConnectionManager sa ws_manager.py (na
    naka-grupo per shop_id). Isang customer ay pwedeng may maraming
    naka-open na device/session nang sabay-sabay (hal. dalawang phone,
    o phone + tablet) — kaya listahan ng connections bawat customer_id,
    hindi iisa lang, parehong pattern ng shop-side na manager.

    Gumagana ito NANG HIWALAY sa ConnectionManager (shop side) — walang
    shared state sa pagitan ng dalawa. Hindi kailangan dito ang
    SessionLocal()/DB session pattern na ginamit sa ConnectionManager.
    _set_shop_online_status(), dahil walang "online status" na
    kailangang i-persist sa Customer model — ang connection presence na
    ito ay purong in-memory delivery mechanism lang, walang side-effect
    sa database.

    NOTE: ang FastAPI WebSocket ROUTE (`@router.websocket("/ws/customer")`)
    ay NASA booking_routes.py, HINDI dito — ang file na ito ay dapat
    naglalaman lang ng manager class, walang router/route definitions,
    para maiwasan ang circular import (ang booking_routes.py at
    booking_controller.py ay parehong nag-i-import mula dito).
    """

    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, customer_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.setdefault(customer_id, []).append(websocket)

    def disconnect(self, customer_id: int, websocket: WebSocket):
        connections = self.active_connections.get(customer_id)
        if connections and websocket in connections:
            connections.remove(websocket)

        if connections is not None and not connections:
            self.active_connections.pop(customer_id, None)

    async def send_to_customer(self, customer_id: int, message: dict):
        """
        Ipinapadala ang message sa LAHAT ng naka-connect na device ng
        customer na ito. Kung walang naka-connect (nakasara ang mobile
        app, walang internet, atbp.), tahimik lang itong walang epekto
        — hindi error, dahil ang Notification table
        (notification_controller.create_notification(), laging
        tinatawag BAGO ang push na ito sa lahat ng call sites sa
        booking_controller.py) at ang polling sa GET /bookings/mine
        ang tunay na "source of truth" — hindi dapat umasa nang buo ang
        anumang logic sa successful delivery ng WebSocket push na ito.

        `message["type"]` ay dapat EVENT_BOOKING_UPDATED (o katumbas na
        string) — parehong convention ng ws_manager.py's broadcast().

        Dead connections (na-disconnect na pero hindi pa na-clean up)
        ay tinatanggal na rin dito habang nag-iiterate, parehong
        pattern ng ConnectionManager.broadcast().
        """
        connections = self.active_connections.get(customer_id, [])
        dead_connections = []
        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)
        for dead in dead_connections:
            self.disconnect(customer_id, dead)


customer_manager = CustomerConnectionManager()