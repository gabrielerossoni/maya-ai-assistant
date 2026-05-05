from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
        # Loop uvicorn (lifespan): necessario per run_coroutine_threadsafe da altri thread
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.state_cache: dict = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        
        # Send cached state to newly connected client
        for msg in self.state_cache.values():
            try:
                await websocket.send_json(msg)
            except Exception:
                pass

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Invia un dizionario JSON a tutti i client connessi (thread-safe)."""
        # Cache message state for new connections
        msg_type = message.get("type")
        if msg_type in ["news", "weather", "spotify", "arduino_event"]:
            self.state_cache[msg_type] = message
            
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
