from typing import Dict, List
from fastapi import WebSocket


class ConnectionManager:
    """
    Nagtatrack ng mga aktibong WebSocket connections, naka-grupo per
    shop_id. Isang shop ay pwedeng magkaroon ng maraming naka-open na
    Service Terminal tabs/devices nang sabay-sabay (hal. dalawang staff,
    magkaibang computer) — kaya listahan ng connections bawat shop_id,
    hindi iisa lang.
    """

    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, shop_id: int):
        await websocket.accept()
        self.active_connections.setdefault(shop_id, []).append(websocket)

    def disconnect(self, websocket: WebSocket, shop_id: int):
        connections = self.active_connections.get(shop_id)
        if connections and websocket in connections:
            connections.remove(websocket)
        if connections is not None and not connections:
            self.active_connections.pop(shop_id, None)

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


manager = ConnectionManager()