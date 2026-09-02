from typing import Dict, List
from fastapi import WebSocket
from app.database import SessionLocal
from app import models


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
        walang epekto — hindi error, dahil GET /bookings/awaiting-approval
        pa rin ang sisiguradong makikita ang booking sa susunod na page
        load/refresh.
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