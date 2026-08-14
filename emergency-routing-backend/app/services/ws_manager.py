from fastapi import WebSocket


class ConnectionManager:
    """Tracks live WebSocket connections keyed by hospital_id / ambulance_id.

    Note: this is an in-memory, single-process implementation. It will not
    scale past one server process (connections and broadcasts are local to the
    instance). For multi-instance deployments, replace it with Redis pub/sub
    (or a similar broker) so a broadcast on one instance reaches subscribers
    connected to any instance.
    """

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, key: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(key, set()).add(websocket)

    def disconnect(self, key: str, websocket: WebSocket) -> None:
        connections = self._connections.get(key)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            self._connections.pop(key, None)

    async def broadcast_to_key(self, key: str, message: dict) -> None:
        for websocket in list(self._connections.get(key, ())):
            await websocket.send_json(message)


manager = ConnectionManager()
