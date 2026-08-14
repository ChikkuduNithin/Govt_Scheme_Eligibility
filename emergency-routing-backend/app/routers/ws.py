import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.services.ws_manager import manager

router = APIRouter(tags=["websockets"])


async def _keepalive_loop(websocket: WebSocket) -> None:
    """Read until disconnect, sending periodic pings to keep the connection alive."""
    try:
        while True:
            try:
                await asyncio.wait_for(
                    websocket.receive_text(), timeout=settings.WS_KEEPALIVE_SECONDS
                )
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass


@router.websocket("/ws/hospital/{hospital_id}")
async def hospital_websocket(websocket: WebSocket, hospital_id: str) -> None:
    """Hospital dashboard subscription channel for incoming alerts.

    The hospital dashboard keeps this connection open; the server pushes
    `hospital_alerts` documents over it as they are created.
    """
    await manager.connect(hospital_id, websocket)
    try:
        await _keepalive_loop(websocket)
    finally:
        manager.disconnect(hospital_id, websocket)


@router.websocket("/ws/ambulance/{ambulance_id}")
async def ambulance_websocket(websocket: WebSocket, ambulance_id: str) -> None:
    """Ambulance app subscription channel for re-routing updates.

    When a hospital rejects an alert, the server pushes the updated
    recommendation over this channel so the crew sees the new destination.
    """
    await manager.connect(ambulance_id, websocket)
    try:
        await _keepalive_loop(websocket)
    finally:
        manager.disconnect(ambulance_id, websocket)
