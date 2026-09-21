from fastapi import WebSocket, WebSocketDisconnect, Query
from app.services.customer_ws_manager import customer_manager
from app.security import decode_supabase_token
from app import models
from app.database import get_db


@router.websocket("/ws/customer")
async def customer_websocket(
    websocket: WebSocket,
    token: str = Query(...),
):
    """
    Mobile app WebSocket connection — kailangan ipasa ang Supabase JWT
    bilang query param (?token=...) dahil hindi native na sumusuporta
    ang WebSocket protocol sa Authorization headers gaya ng REST.

    Ginagamit ito ng order_tracking_page.dart (o katumbas) bilang
    live-update channel — sa sandaling magbago ang booking status,
    ma-finalize ang presyo, o ma-verify/i-reject ang payment mula sa
    shop, agad na matatanggap ng customer ang "booking_updated" event
    dito (see customer_manager.send_to_customer() calls sa
    booking_controller.py).
    """
    db = next(get_db())
    try:
        claims = decode_supabase_token(token)
        supabase_uid = claims.get("sub")
        customer = db.query(models.Customer).filter(
            models.Customer.supabase_uid == supabase_uid
        ).first()

        if not customer or not customer.is_active:
            await websocket.close(code=4401)
            return

        await customer_manager.connect(customer.id, websocket)

        try:
            while True:
                # Keep the connection alive; the client doesn't need to
                # send anything meaningful — this just waits for a
                # disconnect signal.
                await websocket.receive_text()
        except WebSocketDisconnect:
            customer_manager.disconnect(customer.id, websocket)

    finally:
        db.close()