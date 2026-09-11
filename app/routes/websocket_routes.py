from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, HTTPException

from app.services.ws_manager import manager
from app.security import decode_supabase_token
from app.database import SessionLocal
from app import models

router = APIRouter(tags=["Notifications (WebSocket)"])


@router.websocket("/ws/notifications")
async def notifications_websocket(websocket: WebSocket, token: str = Query(...)):
    """
    Real-time notification channel para sa Service Terminal. Kinokonekta
    ito ng web app gamit ang: wss://.../ws/notifications?token=<JWT>

    Query param na "token" dahil hindi pwedeng maglagay ng Authorization
    header ang browser's native WebSocket API — ito ang standard
    workaround. Same Supabase-issued access token lang gamit dito
    (galing sa parehong login), kaya walang bagong auth mechanism na
    kailangang i-maintain.

    UPDATED (Supabase Auth migration): decode_access_token() (na
    gumagamit ng sariling SECRET_KEY at naglalagay ng custom claims
    tulad ng "type" at "shop_id" direkta sa token) ay pinalitan ng
    decode_supabase_token(). Ang Supabase-issued token ay WALANG
    "type"/"shop_id" claim — "sub" (ang supabase_uid) lang ang
    meron. Kaya kailangan na natin mismong i-query ang User table via
    supabase_uid dito (parehong pattern gaya ng get_current_user() sa
    security.py) para makuha ang shop_id.

    NOTE: hindi natin puwedeng gamitin ang Depends(get_current_user)
    dito dahil WebSocket route ito, hindi regular HTTP route na may
    Authorization header — ang token ay dumarating bilang query param,
    kaya manual ang pag-decode + pag-query sa DB.

    NOTE: Ang connect()/disconnect() calls dito (papunta sa
    ws_manager.manager) ang siya ring nag-a-update sa Shop.is_online —
    walang dagdag na logic na kailangan dito sa route mismo. Kapag
    nag-open ng Service Terminal tab ang isang shop, "online" agad ito;
    kapag na-close/na-disconnect ang lahat ng tabs, "offline" agad.
    """
    db = SessionLocal()
    try:
        try:
            claims = decode_supabase_token(token)
        except HTTPException:
            await websocket.close(code=4401)
            return

        supabase_uid = claims.get("sub")
        if supabase_uid is None:
            await websocket.close(code=4401)
            return

        user = db.query(models.User).filter(models.User.supabase_uid == supabase_uid).first()
        if user is None or not user.is_active:
            await websocket.close(code=4401)
            return

        shop_id = user.shop_id
        if shop_id is None:
            await websocket.close(code=4403)
            return
    finally:
        db.close()

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