from fastapi import WebSocket
import json


class WebSocketManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Invia un dizionario JSON a tutti i client connessi (thread-safe)."""
        # Crea snapshot della lista per iterare in sicurezza
        connections_snapshot = list(self.active_connections)
        dead_connections = []
        
        for connection in connections_snapshot:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)
        
        # Pulisci le connessioni morte
        for connection in dead_connections:
            self.disconnect(connection)


manager = WebSocketManager()
