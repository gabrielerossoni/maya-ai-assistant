"""
FastAPI routes e WebSocket handler.
Estratto da main.py per ridurre la complessità del punto di ingresso.
"""

import asyncio
import os

from fastapi import WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

import core.broadcasters as _bc
from core.broadcasters import (
    broadcast_state,
    broadcast_weather_update,
    client_lat,
    client_lon,
    execute_and_broadcast,
)
from core.log_utils import setup_dashboard_log_filter

# Flag globale per applicare il filtro log una sola volta
_log_filter_applied = False


# ---------------------------------------------------------------------------
# HTTP routes
# ---------------------------------------------------------------------------
async def get_dashboard():
    return FileResponse("static/maya_dashboard.html")


async def get_service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")


async def get_manifest():
    return FileResponse("static/manifest.json", media_type="application/manifest+json")


async def health_check():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
async def websocket_endpoint(websocket: WebSocket, agent, manager, voice_manager, MODELS):
    global _log_filter_applied
    try:
        await manager.connect(websocket)

        # Applica il filtro log al primo collegamento del client (una sola volta)
        if not _log_filter_applied:
            setup_dashboard_log_filter(manager)
            _log_filter_applied = True

        await broadcast_state(agent, manager, MODELS)
        try:
            await websocket.send_json(voice_manager.voice_status_message())
        except Exception:
            pass

        # Invio immediato del meteo corrente (utilizzando le coordinate memorizzate o il fallback)
        asyncio.create_task(broadcast_weather_update(agent, manager, _bc.client_lat, _bc.client_lon))

        while True:
            try:
                data = await websocket.receive_json()
                if data.get("type") == "command":
                    cmd = data.get("text", "")
                    if cmd:
                        # Invia la richiesta dell'utente alla dashboard tramite print (che passa dal filtro)
                        print(f"Richiesta: {cmd}")
                        asyncio.create_task(execute_and_broadcast(cmd, agent, manager))
                elif data.get("type") == "geolocation":
                    if os.environ.get("MAYA_SKIP_BROWSER_OPEN") != "1":
                        lat = data.get("lat")
                        lon = data.get("lon")
                        if lat is not None and lon is not None:
                            _bc.client_lat = lat
                            _bc.client_lon = lon
                            asyncio.create_task(broadcast_weather_update(agent, manager, lat, lon))
                elif data.get("type") == "tool":
                    # Esecuzione diretta tool, bypassa LLM
                    action = data.get("action", {})
                    if action:
                        result = await agent.tool_manager.execute(action)
                        if action.get("tool") == "calendar" and "events" in result:
                            await manager.broadcast(
                                {
                                    "type": "calendar_data",
                                    "events": result.get("events", []),
                                }
                            )
                        elif action.get("tool") == "trading" and result.get("status") == "ok":
                            rdata = result.get("data", {})
                            if rdata.get("overview"):
                                # Broadcast ogni item singolarmente (accumulator nel frontend)
                                for item in rdata.get("items", []):
                                    await manager.broadcast({"type": "trading", **item})
                            else:
                                await manager.broadcast({"type": "trading", **rdata})
                        elif action.get("tool") == "spotify":
                            # Dopo next/prev/play_pause, aggiorna widget con brano corrente
                            await asyncio.sleep(0.5)  # attendi che Spotify aggiorni lo stato
                            current = await agent.tool_manager.execute({"tool": "spotify", "command": "current"})
                            await manager.broadcast(
                                {
                                    "type": "spotify",
                                    "track": current.get("track", ""),
                                    "artist": current.get("artist", ""),
                                    "album_art": current.get("album_art", ""),
                                    "is_playing": current.get("is_playing", False),
                                }
                            )
                        else:
                            await manager.broadcast(
                                {
                                    "type": "log",
                                    "text": result.get("message", ""),
                                    "level": "ok",
                                }
                            )
                        await broadcast_state(agent, manager, MODELS)
            except WebSocketDisconnect:
                break
            except RuntimeError as e:
                err = str(e).lower()
                if "accept" in err or "not connected" in err or "disconnect" in err:
                    break
                raise
            except Exception as e:
                print(f"[WebSocket] Errore durante receive: {e}")
                break
    except Exception as e:
        print(f"[WebSocket] Errore connessione: {e}")
    finally:
        manager.disconnect(websocket)
