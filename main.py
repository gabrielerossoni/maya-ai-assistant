"""
MAYA - Sistema AI Agentico Locale
Punto di ingresso principale

Questo file contiene solo il wiring: crea le istanze, registra le route,
definisce il lifespan e avvia uvicorn.
La logica è nei moduli core/*.py.
"""

import asyncio
import os
import sys
import threading
import time
import webbrowser

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
import uvicorn

from core.agent_core import AgentCore, MODELS
from core.plugin_loader import PluginLoader
from core.proactive_manager import ProactiveManager
from tools.display_tool import DisplayTool
from core.websocket_manager import manager
from core.voice_manager import VoiceManager
from core.ollama_manager import ensure_ollama_running
from core.ngrok_manager import start_ngrok
from core.server_utils import pick_http_port, print_banner
from core.broadcasters import (
    interactive_console,
    stats_broadcaster,
    spotify_broadcaster,
    news_broadcaster,
    weather_broadcaster,
    sensor_broadcaster,
    broadcast_state,
)
from core.routes import (
    get_dashboard,
    get_service_worker,
    get_manifest,
    health_check,
    websocket_endpoint,
)

# ---------------------------------------------------------------------------
# Variabili globali per i task in background
# ---------------------------------------------------------------------------
_bg_tasks = []


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print_banner()
    # Imposta il loop prima di ogni altra cosa
    try:
        agent.loop = asyncio.get_running_loop()
    except RuntimeError:
        agent.loop = asyncio.get_event_loop()
    manager.loop = agent.loop
    # Segnala che il loop è pronto per VoiceManager
    voice_manager.set_loop_ready()

    # Recupera la porta HTTP configurata
    http_port = int(os.environ.get("MAYA_HTTP_PORT", "8000"))

    await agent.initialize()

    # Avvia ngrok
    ngrok_url = await asyncio.to_thread(start_ngrok, http_port)
    if ngrok_url:
        print(f"\n{'='*50}")
        print(f"  \U0001f310 MAYA pubblica su: {ngrok_url}")
        print(f"{'='*50}\n")
    else:
        print("[NGROK] Tunnel non avviato, solo accesso locale.")

    # Inizializza PluginLoader e ProactiveManager
    plugins_dir = os.path.join(os.getcwd(), "plugins")
    os.makedirs(plugins_dir, exist_ok=True)

    plugin_loader = PluginLoader(agent.tool_manager, plugins_dir)
    plugin_loader.start()

    proactive_manager = ProactiveManager(agent.tool_manager, manager, memory_manager=agent.memory)
    asyncio.create_task(proactive_manager.start_loop())

    # Inietta WebSocketManager nel mqtt_tool per broadcast bidirezionale
    mqtt_tool = agent.tool_manager.tools.get("mqtt")
    if mqtt_tool and hasattr(mqtt_tool, "set_ws_manager"):
        mqtt_tool.set_ws_manager(manager, agent.loop)

    # display.start()  # Disabilitato: conflitto stdout con console interattiva. Stato inviato via WebSocket

    # Avvia la console e i broadcaster in background
    global _bg_tasks
    _bg_tasks = [
        asyncio.create_task(interactive_console(agent, manager)),
        asyncio.create_task(stats_broadcaster(manager, voice_manager)),
        asyncio.create_task(spotify_broadcaster(agent, manager)),
        asyncio.create_task(news_broadcaster(agent, manager)),
        asyncio.create_task(weather_broadcaster(agent, manager)),
        asyncio.create_task(sensor_broadcaster(agent, manager)),
    ]

    # Apri il browser con un piccolo ritardo (il server deve essere pronto)
    def _open_browser():
        if os.environ.get("MAYA_SKIP_BROWSER_OPEN") == "1":
            return
        time.sleep(1.5)
        # Cache-buster per forzare il ricaricamento della dashboard
        webbrowser.open(f"http://127.0.0.1:{http_port}/?v={int(time.time())}")

    threading.Thread(target=_open_browser, daemon=True).start()

    # Avvia il sistema vocale
    try:
        voice_manager.start()
    except Exception as e:
        print(f"[VOICE] Impossibile avviare il sistema vocale: {e}")
        import traceback

        traceback.print_exc()

    # Registra hook Arduino per eventi push
    arduino_tool = agent.tool_manager.tools.get("arduino")
    if arduino_tool:

        _main_loop = asyncio.get_running_loop()  # cattura il loop del lifespan

        def arduino_event_handler(event: dict):
            try:
                if "telemetry" in event or event.get("type") == "telemetry":
                    telemetry_data = event.copy()
                    telemetry_data.pop("type", None)
                    payload = {
                        "type": "arduino_event",
                        "telemetry": telemetry_data
                    }
                else:
                    payload = {
                        "type": "arduino_event",
                        **event
                    }

                asyncio.run_coroutine_threadsafe(
                    manager.broadcast(payload),
                    _main_loop,
                )
            except Exception as e:
                print(f"[ARDUINO] Event handler error: {e}")

        arduino_tool.register_event_hook(arduino_event_handler)

    try:
        yield
    finally:
        # Shutdown
        print("\n[SYSTEM] Spegnimento in corso...")
        display.stop()
        # Cancella i task in background al termine
        for task in _bg_tasks:
            task.cancel()

        # Tool Cleanup
        for name, tool in agent.tool_manager.tools.items():
            if hasattr(tool, "close"):
                try:
                    tool.close()
                except Exception as e:
                    print(f"[SHUTDOWN] Errore in chiusura tool {name}: {e}")


# ---------------------------------------------------------------------------
# Istanze globali
# ---------------------------------------------------------------------------
app = FastAPI(lifespan=lifespan)
agent = AgentCore()
agent.socket_manager = manager
display = DisplayTool()
voice_manager = VoiceManager(agent, manager)


# ---------------------------------------------------------------------------
# Route HTTP
# ---------------------------------------------------------------------------
@app.get("/")
async def _dashboard():
    return await get_dashboard()


@app.get("/sw.js")
async def _sw():
    return await get_service_worker()


@app.get("/manifest.json")
async def _manifest():
    return await get_manifest()


@app.get("/health")
async def _health():
    return await health_check()


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.websocket("/ws")
async def _ws(websocket: WebSocket):
    await websocket_endpoint(websocket, agent, manager, voice_manager, MODELS)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    from core.instance_guard import (
        LOCK_PORT,
        InstanceGuard,
        install_signal_handlers,
        kill_existing,
        skip_guard,
    )

    if len(sys.argv) > 1 and sys.argv[1].lower() == "kill":
        sys.exit(0 if kill_existing() else 1)

    if not skip_guard():
        _instance_guard = InstanceGuard()
        if not _instance_guard.acquire():
            print(
                "[MAYA] \u00c8 gi\u00e0 attiva un'istanza (lock su 127.0.0.1:"
                f"{LOCK_PORT}).\n"
                "       Per chiuderla:  python main.py kill\n"
                "       Bypass (solo debug):  MAYA_SKIP_INSTANCE_GUARD=1\n"
            )
            sys.exit(1)
        install_signal_handlers(_instance_guard)

    _http_host = "127.0.0.1"
    _http_port = pick_http_port(_http_host)
    if _http_port != int(os.environ.get("MAYA_PORT", "8000")):
        print(
            f"[MAYA] Porta {os.environ.get('MAYA_PORT', '8000')} occupata: "
            f"avvio su http://{_http_host}:{_http_port} (chiudi le altre istanze se non serve)."
        )
    os.environ["MAYA_HTTP_PORT"] = str(_http_port)

    threading.Thread(target=ensure_ollama_running, daemon=True).start()
    try:
        uvicorn.run(
            "main:app",
            host=_http_host,
            port=_http_port,
            log_level="warning",
        )
    except OSError as e:
        if getattr(e, "winerror", None) == 10048 or getattr(e, "errno", None) in (
            10048,
            98,
        ):
            print(
                "\n[MAYA] Porta ancora occupata: chiudi l'altra istanza, "
                "oppure imposta MAYA_PORT=8010 (o MAYA_PORT_STRICT=1 per forzare una sola porta).\n"
            )
        raise
