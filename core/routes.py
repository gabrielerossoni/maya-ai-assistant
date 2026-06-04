"""
FastAPI routes e WebSocket handler.
Estratto da main.py per ridurre la complessità del punto di ingresso.
"""

import asyncio
import os
import time

import httpx
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

_NEWS_LIVE_GROUPS = [
    [
        {"src": "UCNye-wNBqNL5ZzHSJj3l8Bg", "label": "AL JAZEERA"},
        {"src": "UC7fWeaHhqgM4Ry-RMpM2YYw", "label": "TRT WORLD"},
        {"src": "UCQfwfsi5VrQ8yKZ-UWmAEFg", "label": "FRANCE 24"},
        {"src": "UCSrZ3UV4jOidv8ppoVuvW9Q", "label": "EURONEWS"},
    ],
    [
        {"src": "UC7fWeaHhqgM4Ry-RMpM2YYw", "label": "TRT WORLD"},
        {"src": "UCQfwfsi5VrQ8yKZ-UWmAEFg", "label": "FRANCE 24"},
        {"src": "UCSrZ3UV4jOidv8ppoVuvW9Q", "label": "EURONEWS"},
        {"src": "UCNye-wNBqNL5ZzHSJj3l8Bg", "label": "AL JAZEERA"},
    ],
    [
        {"src": "UCQfwfsi5VrQ8yKZ-UWmAEFg", "label": "FRANCE 24"},
        {"src": "UCSrZ3UV4jOidv8ppoVuvW9Q", "label": "EURONEWS"},
        {"src": "UC7fWeaHhqgM4Ry-RMpM2YYw", "label": "TRT WORLD"},
        {"src": "UCNye-wNBqNL5ZzHSJj3l8Bg", "label": "AL JAZEERA"},
    ],
    [
        {"src": "UCSrZ3UV4jOidv8ppoVuvW9Q", "label": "EURONEWS"},
        {"src": "UCQfwfsi5VrQ8yKZ-UWmAEFg", "label": "FRANCE 24"},
        {"src": "UC7fWeaHhqgM4Ry-RMpM2YYw", "label": "TRT WORLD"},
        {"src": "UCNye-wNBqNL5ZzHSJj3l8Bg", "label": "AL JAZEERA"},
    ],
]
_news_live_cache = {"ts": 0.0, "streams": []}

_DIRECT_TOOL_ALLOWLIST = {
    "arduino": {
        "ops": {"SET", "GET"},
        "targets": {
            "light",
            "servo",
            "servo2",
            "rgb",
            "rgb1",
            "rgb2",
            "rgb3",
            "neopixel",
            "buzzer",
            "buzzer2",
            "speaker",
            "sensor_read",
            "status",
        },
    },
    "calendar": {"actions": {"list"}},
    "spotify": {
        "commands": {
            "play_pause",
            "play",
            "pause",
            "next",
            "prev",
            "current",
            "volume_up",
            "volume_down",
            "volume",
            "search",
        }
    },
    "trading": {
        "operations": {
            "price",
            "chart",
        }
    },
}


def _validate_direct_tool_action(action: dict) -> tuple[bool, str]:
    """Limita i tool eseguibili direttamente dalla dashboard via WebSocket."""
    if not isinstance(action, dict):
        return False, "azione non valida"

    tool_name = action.get("tool")
    rule = _DIRECT_TOOL_ALLOWLIST.get(tool_name)
    if rule is None:
        return False, f"tool diretto non consentito: {tool_name}"

    if tool_name == "arduino":
        op = str(action.get("op", "SET")).upper()
        target = action.get("target")
        if op not in rule["ops"]:
            return False, f"operazione Arduino non consentita: {op}"
        if target not in rule["targets"]:
            return False, f"target Arduino non consentito: {target}"

    elif tool_name == "calendar":
        if action.get("action") not in rule["actions"]:
            return False, "solo la lettura calendario e' consentita via dashboard"

    elif tool_name == "spotify":
        if action.get("command") not in rule["commands"]:
            return False, f"comando Spotify non consentito: {action.get('command')}"

    elif tool_name == "trading":
        if action.get("operation") not in rule["operations"]:
            return False, f"operazione trading non consentita: {action.get('operation')}"

    return True, ""


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


async def _youtube_live_channel_available(client: httpx.AsyncClient, channel_id: str) -> bool:
    live_url = f"https://www.youtube.com/channel/{channel_id}/live"
    oembed_url = f"https://www.youtube.com/oembed?url={live_url}&format=json"
    try:
        res = await client.get(oembed_url)
        if res.status_code != 200:
            return False

        page = await client.get(live_url)
        if page.status_code != 200:
            return False

        html = page.text.lower()
        upcoming_markers = (
            '"isupcoming":true',
            '"upcomingeventdata"',
            '"scheduledstarttime"',
            "premiere",
            "waiting room",
            "set reminder",
            "notify me",
        )
        if any(marker in html for marker in upcoming_markers):
            return False

        live_markers = (
            '"islivenow":true',
            '"islive":true',
            '"badges":[{"metadataBadgeRenderer":{"style":"BADGE_STYLE_TYPE_LIVE_NOW"',
            "badge_style_type_live_now",
        )
        return any(marker in html for marker in live_markers)
    except httpx.HTTPError:
        return False


async def _select_news_live_streams(groups=None, checker=None):
    groups = groups or _NEWS_LIVE_GROUPS
    checker = checker or _youtube_live_channel_available
    check_timeout = float(os.environ.get("MAYA_NEWS_LIVE_CHECK_TIMEOUT", "4.0"))
    check_concurrency = max(1, int(os.environ.get("MAYA_NEWS_LIVE_CHECK_CONCURRENCY", "4")))

    async with httpx.AsyncClient(
        timeout=3.0,
        headers={"User-Agent": "MAYA-dashboard/1.0"},
        follow_redirects=True,
    ) as client:
        unique_sources = []
        seen_sources = set()
        for group in groups:
            for candidate in group:
                src = candidate["src"]
                if src not in seen_sources:
                    unique_sources.append(src)
                    seen_sources.add(src)

        semaphore = asyncio.Semaphore(check_concurrency)

        async def _check_channel(src):
            async with semaphore:
                try:
                    return src, await asyncio.wait_for(checker(client, src), timeout=check_timeout)
                except (asyncio.TimeoutError, httpx.HTTPError):
                    return src, False

        availability = dict(await asyncio.gather(*(_check_channel(src) for src in unique_sources)))
        selected = []
        used = set()

        def _select_group(group, used_sources):
            if not group:
                return None

            for index, candidate in enumerate(group):
                if candidate["src"] in used_sources:
                    continue
                if availability.get(candidate["src"]):
                    return {**candidate, "fallback": index > 0}

            fallback = next(
                (
                    candidate
                    for index, candidate in enumerate(group)
                    if index > 0 and candidate["src"] not in used_sources
                ),
                None,
            )
            if fallback is None:
                fallback = next((candidate for candidate in group if candidate["src"] not in used_sources), None)
            if fallback is None:
                return None
            return {**fallback, "fallback": True, "unavailable": True}

        for group in groups:
            stream = _select_group(group, used)
            if stream is None:
                continue
            selected.append(stream)
            used.add(stream["src"])

        return selected


async def get_news_live_streams():
    now = time.monotonic()
    if _news_live_cache["streams"] and now - _news_live_cache["ts"] < 120:
        return {"status": "ok", "mode": "live_channel_fallback", "streams": _news_live_cache["streams"]}

    streams = await _select_news_live_streams()
    _news_live_cache["ts"] = now
    _news_live_cache["streams"] = streams
    return {"status": "ok", "mode": "live_channel_fallback", "streams": streams}


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

        # Send initial chat log history
        turns = await agent.memory.get_all()
        if turns:
            try:
                await websocket.send_json({"type": "history", "turns": turns})
            except Exception:
                pass

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
                        allowed, reason = _validate_direct_tool_action(action)
                        if not allowed:
                            await manager.broadcast(
                                {
                                    "type": "log",
                                    "text": f"Azione dashboard bloccata: {reason}",
                                    "level": "error",
                                }
                            )
                            continue
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
