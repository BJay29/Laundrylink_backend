from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException

from app.services.ws_manager import manager
from app.security import decode_access_token

router = APIRouter(tags=["Notifications (WebSocket)"])


@router.websocket("/ws/notifications")
async def notifications_websocket(websocket: WebSocket, token: str = Query(...)):
    """
    Real-time notification channel para sa Service Terminal. Kinokonekta
    ito ng web app gamit ang: wss://.../ws/notifications?token=<JWT>

    Query param na "token" dahil hindi pwedeng maglagay ng Authorization
    header ang browser's native WebSocket API — ito ang standard
    workaround. Same JWT lang gamit dito (galing sa parehong login),
    kaya walang bagong auth mechanism na kailangang i-maintain.

    NOTE: Ang connect()/disconnect() calls dito (papunta sa
    ws_manager.manager) ang siya ring nag-a-update sa Shop.is_online —
    walang dagdag na logic na kailangan dito sa route mismo. Kapag
    nag-open ng Service Terminal tab ang isang shop, "online" agad ito;
    kapag na-close/na-disconnect ang lahat ng tabs, "offline" agad.
    """
    try:
        payload = decode_access_token(token)
        if payload.get("type") != "user":
            await websocket.close(code=4403)
            return
        shop_id = payload.get("shop_id")
        if shop_id is None:
            await websocket.close(code=4401)
            return
    except HTTPException:
        await websocket.close(code=4401)
        return

    await manager.connect(websocket, shop_id)
    try:
        while True:
            # Wala talagang ginagawa dito sa mensahe mula sa client —
            # ang connection lang mismo ang ginagamit para ma-detect
            # kung online pa ba (naka-open ang tab) para makatanggap
            # ng broadcast(). Kailangan lang itong "await" ng something
            # para ma-detect ang disconnect (WebSocketDisconnect).
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, shop_id)