"""
Task asincroni di broadcasting: meteo, news, stats, spotify, sensori, stato.
Estratto da main.py per ridurre la complessità del punto di ingresso.

Tutte le funzioni ricevono le dipendenze come parametro per evitare import circolari.
"""

import asyncio
import os
import random
import time

import ollama

from core.ollama_manager import _ollama_api_reachable

# ---------------------------------------------------------------------------
# Variabili di stato globali per coordinate client
# ---------------------------------------------------------------------------
client_lat = None
client_lon = None

# ---------------------------------------------------------------------------
# Cache modelli
# ---------------------------------------------------------------------------
_last_models_check: float = 0.0
_cached_models_status: dict = {}


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
async def broadcast_weather_update(agent, manager, lat=None, lon=None):
    """Esegue l'aggiornamento meteo immediato per le coordinate o la località di fallback e lo trasmette."""
    try:
        weather_tool = agent.tool_manager.tools.get("weather")
        if weather_tool:
            if lat is not None and lon is not None:
                action = {"lat": lat, "lon": lon}
            else:
                location = os.getenv("DEFAULT_WEATHER_LOCATION", "Roma")
                action = {"location": location}
            result = await asyncio.to_thread(weather_tool.execute, action)
            if result.get("status") == "ok":
                await manager.broadcast(
                    {"type": "weather", "data": result.get("data")}
                )
            else:
                await manager.broadcast({"type": "weather", "error": True})
    except Exception as e:
        print(f"[WebSocket] Errore meteo immediato: {e}")
        await manager.broadcast({"type": "weather", "error": True})


async def weather_broadcaster(agent, manager):
    """Trasmette il meteo alla dashboard ogni 30 minuti."""
    global client_lat, client_lon
    while True:
        try:
            weather_tool = agent.tool_manager.tools.get("weather")
            if weather_tool:
                # Wrap blocking requests call in a thread
                location = os.getenv("DEFAULT_WEATHER_LOCATION", "Roma")
                action = {"location": location}
                if os.environ.get("MAYA_SKIP_BROWSER_OPEN") != "1":
                    if client_lat is not None and client_lon is not None:
                        action = {"lat": client_lat, "lon": client_lon}
                result = await asyncio.to_thread(weather_tool.execute, action)
                if result.get("status") == "ok":
                    await manager.broadcast(
                        {"type": "weather", "data": result.get("data")}
                    )
                else:
                    await manager.broadcast({"type": "weather", "error": True})
        except Exception as e:
            print(f"[BROADCASTER] Errore meteo: {e}")
            await manager.broadcast({"type": "weather", "error": True})
        await asyncio.sleep(1800)


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------
async def news_broadcaster(agent, manager):
    """Trasmette le ultime notizie alla dashboard ogni 10 minuti."""
    # Aspetta che almeno un client sia connesso prima di caricare le notizie all'avvio
    while not manager.active_connections:
        await asyncio.sleep(1)
    
    # Jitter iniziale per non caricare tutto all'avvio (evita spike CPU/memoria)
    await asyncio.sleep(random.uniform(3, 8))

    while True:
        try:
            # Recupera il news_tool ogni volta dal tool_manager dell'agente globale
            news_tool = agent.tool_manager.tools.get("news")
            if news_tool:
                # Wrap blocking feedparser call in a thread
                result = await asyncio.to_thread(news_tool.execute, {"limit": 10})
                if result.get("status") == "ok":
                    await manager.broadcast(
                        {"type": "news", "articles": result.get("news", [])}
                    )
        except Exception as e:
            print(f"[BROADCASTER] Errore news: {e}")
        await asyncio.sleep(600)


# ---------------------------------------------------------------------------
# Stats (CPU/RAM)
# ---------------------------------------------------------------------------
async def stats_broadcaster(manager, voice_manager):
    import psutil

    # Warm-up: la prima chiamata con interval=None restituisce sempre 0.0
    psutil.cpu_percent(interval=None)
    await asyncio.sleep(2)

    while True:
        try:
            cpu_load = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            stats = {
                "type": "stats",
                "neural_load": cpu_load,
                "memory": memory.percent,
                "ram_used_gb": round(memory.used / (1024**3), 1),
                "ram_total_gb": round(memory.total / (1024**3), 1),
                "uptime": "Online",
                # Allinea widget voce anche se alcuni broadcast si perdono
                "voice_status": voice_manager.get_dashboard_voice_status(),
            }
            await manager.broadcast(stats)
        except:
            pass
        await asyncio.sleep(2)


# ---------------------------------------------------------------------------
# Sensor (Arduino)
# ---------------------------------------------------------------------------
async def sensor_broadcaster(agent, manager):
    while True:
        try:
            arduino_tool = agent.tool_manager.tools.get("arduino")
            if arduino_tool:
                result = await asyncio.to_thread(arduino_tool.get_sensor_data)
                if result is not None:
                    await manager.broadcast({
                        "type": "arduino_event",
                        "telemetry": result,
                    })
        except Exception:
            pass
        await asyncio.sleep(30)


# ---------------------------------------------------------------------------
# Spotify
# ---------------------------------------------------------------------------
SPOTIFY_ENABLED = os.environ.get("SPOTIFY_ENABLED", "true").strip().lower() not in ("0", "false", "no")


async def spotify_broadcaster(agent, manager):
    if not SPOTIFY_ENABLED:
        return
    while True:
        try:
            spotify_tool = agent.tool_manager.tools.get("spotify")
            if spotify_tool and spotify_tool.sp:
                # Wrap blocking spotipy call in a thread
                result = await asyncio.to_thread(spotify_tool._current_track)
                if result["status"] == "ok":
                    await manager.broadcast(
                        {
                            "type": "spotify",
                            "message": result.get("message", ""),
                            "track": result.get("track", ""),
                            "artist": result.get("artist", ""),
                            "is_playing": result.get("is_playing", False),
                            "album_art": result.get("album_art", ""),
                        }
                    )
        except Exception:
            pass
        await asyncio.sleep(3)


# ---------------------------------------------------------------------------
# Models status
# ---------------------------------------------------------------------------
async def get_models_status(MODELS):
    """
    Controlla lo stato di tutti i modelli configurati su Ollama.
    Ritorna un dizionario con il nome del modello e il suo stato (online/offline).
    """
    try:
        # Check if ollama is reachable first to avoid long library timeouts
        if not await _ollama_api_reachable(timeout=0.5):
            return {k: {"name": v, "online": False, "id": k} for k, v in MODELS.items()}

        client = ollama.AsyncClient()
        # Timeout di 2 secondi per evitare blocchi infiniti se ollama è appeso
        local_models = await asyncio.wait_for(client.list(), timeout=2.0)
        downloaded = [m.get("name", "") for m in local_models.get("models", [])]

        status = {}
        for key, name in MODELS.items():
            # Controlla se il modello esatto o una variante è disponibile
            is_ok = any(name in d or d in name for d in downloaded)
            status[key] = {"name": name, "online": is_ok, "id": key}
        return status
    except (asyncio.TimeoutError, Exception) as e:
        if not isinstance(e, asyncio.TimeoutError):
            print(f"[MONITOR] Errore nel controllo modelli: {e}")
        # Ritorna tutti i modelli come offline se c'è un errore o timeout
        return {k: {"name": v, "online": False, "id": k} for k, v in MODELS.items()}


# ---------------------------------------------------------------------------
# System state
# ---------------------------------------------------------------------------
async def broadcast_state(agent, manager, MODELS):
    """
    Trasmette lo stato del sistema alla dashboard, includendo:
    - Stato dei modelli (online/offline)
    - Stato di Ollama
    - Informazioni di sistema
    """
    global _last_models_check, _cached_models_status
    arduino_tool = agent.tool_manager.tools.get("arduino")
    now = time.time()
    if now - _last_models_check > 30:
        _cached_models_status = await get_models_status(MODELS)
        _last_models_check = now
    models_status = _cached_models_status
    ollama_online = any(m.get("online", False) for m in models_status.values())

    _debug_reset_client = os.environ.get(
        "MAYA_DEBUG_RESET_CLIENT", ""
    ).strip().lower() in ("1", "true", "yes")

    state_payload = {
        "type": "state",
        "cmdCount": len(agent.memory.turns) // 2 if hasattr(agent, "memory") else 0,
        "memTurns": len(agent.memory.turns) if hasattr(agent, "memory") else 0,
        "ollama": "ONLINE" if ollama_online else "OFFLINE",
        "models": models_status,
        "led": (
            arduino_tool.sim_state.get("light", "OFF")
            if isinstance(arduino_tool.sim_state.get("light"), str)
            else ("ON" if arduino_tool.sim_state.get("light") else "OFF")
        ).lower(),
        "servo": (
            arduino_tool.sim_state.get("servo", "CLOSED")
            if isinstance(arduino_tool.sim_state.get("servo"), str)
            else str(arduino_tool.sim_state.get("servo"))
        ).lower(),
        "servo2": (
            arduino_tool.sim_state.get("servo2", 0)
            if isinstance(arduino_tool.sim_state.get("servo2"), int)
            else 0
        ),
        "rgb1":   list(arduino_tool.sim_state.get("rgb1", [0, 0, 0])),
        "rgb2":   list(arduino_tool.sim_state.get("rgb2", [0, 0, 0])),
        "rgb3":   list(arduino_tool.sim_state.get("rgb3", [0, 0, 0])),
        "buzzer": bool(arduino_tool.sim_state.get("buzzer", False)),
        "system": {
            "model": MODELS.get("router", "llama3.2").upper(),
            "name": os.getenv("ASSISTANT_NAME", "MAYA"),
            "version": "2.0.1-dev",
            "reset_storage": _debug_reset_client,
        },
    }
    await manager.broadcast(state_payload)


# ---------------------------------------------------------------------------
# Console interattiva
# ---------------------------------------------------------------------------
async def interactive_console(agent, manager):
    """Legge i comandi dal terminale e li processa."""
    from core.log_utils import user_log

    print("\n[MAYA] Sistema pronto. Digita un comando o 'exit' per uscire.\n")
    loop = asyncio.get_running_loop()
    while True:
        try:
            import sys as _sys

            _sys.stdout.write("MAYA > ")
            _sys.stdout.flush()
            user_input = await loop.run_in_executor(None, _sys.stdin.readline)
            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.lower() in ["exit", "quit", "esci"]:
                print("[MAYA] Spegnimento in corso...")
                os._exit(0)

            # Invia il comando dal terminale come se venisse dalla dashboard
            print(f"Richiesta: {user_input}")
            full_reply = ""
            layout_data = {"type": "orb", "params": {}}
            try:
                async for token in agent.process(user_input):
                    full_reply += token

                task = asyncio.current_task()
                if task and task in agent._current_task_final_data:
                    _, layout_data = agent._current_task_final_data.pop(task)
                elif hasattr(agent, "_last_final_data"):
                    _, layout_data = agent._last_final_data
            except Exception as e:
                print(f"[CONSOLE] Errore: {e}")

            await manager.broadcast(
                {
                    "type": "layout",
                    "layout": layout_data.get("type", "orb"),
                    "params": layout_data.get("params", {}),
                }
            )
            print(f"MAYA > {full_reply}")

        except EOFError:
            # Terminale chiuso
            break
        except Exception as e:
            user_log(f"Errore comando: {e}", is_error=True)


# ---------------------------------------------------------------------------
# Execute and broadcast (bridge agent -> dashboard)
# ---------------------------------------------------------------------------
async def execute_and_broadcast(cmd: str, agent, manager):
    """
    Esegue il comando tramite agent.process() e trasmette la risposta in streaming.
    """
    from core.agent_core import MODELS

    # Callback per inviare il filler message al frontend quando elabora
    async def send_progress(msg: str):
        await manager.broadcast(
            {"type": "log", "text": f"🤖 MAYA: {msg}", "level": "info"}
        )

    # Streaming dei token
    full_reply = ""
    # Inizia con l'emoji
    await manager.broadcast(
        {"type": "stream", "token": "🤖 MAYA: ", "full_text": "🤖 MAYA: "}
    )
    full_reply = "🤖 MAYA: "

    layout_data = {"type": "orb", "params": {}}
    try:
        async for token in agent.process(cmd, progress_cb=send_progress):
            full_reply += token
            await manager.broadcast(
                {"type": "stream", "token": token, "full_text": full_reply}
            )

        # Dopo la fine del generatore, recuperiamo i dati finali dall'attributo dell'agente
        task = asyncio.current_task()
        if task and task in agent._current_task_final_data:
            _, layout_data = agent._current_task_final_data.pop(task)
        elif hasattr(agent, "_last_final_data"):
            _, layout_data = agent._last_final_data

    except Exception as e:
        print(f"[PROCESS] Errore: {e}")

    # Invia il layout finale alla dashboard
    await manager.broadcast(
        {
            "type": "layout",
            "layout": layout_data.get("type", "orb"),
            "params": layout_data.get("params", {}),
        }
    )

    print(f"MAYA > {full_reply}")

    # Aggiorna lo stato del sistema (modelli, stats, ecc)
    await broadcast_state(agent, manager, MODELS)
