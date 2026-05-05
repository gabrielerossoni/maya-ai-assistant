"""
MAYA - Sistema AI Agentico Locale
Punto di ingresso principale
"""

import asyncio
import sys
import os
import time
import socket
import shutil
import subprocess
import threading
import webbrowser
import ollama
from core.agent_core import AgentCore, MODELS
from core.plugin_loader import PluginLoader
from core.proactive_manager import ProactiveManager
from tools.display_tool import DisplayTool
from core.websocket_manager import WebSocketManager
from core.log_utils import setup_dashboard_log_filter, user_log
from core.voice_manager import VoiceManager
from core.websocket_manager import manager
# Variabili globali per i task in background
_bg_tasks = []
_log_filter_applied = False

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1")
OLLAMA_PORT = int(os.environ.get("OLLAMA_PORT", "11434"))


def _ollama_addr() -> tuple[str, int]:
    host = OLLAMA_HOST
    if host.startswith("http://"):
        host = host[7:]
    elif host.startswith("https://"):
        host = host[8:]
    host = host.split("/")[0]
    if ":" in host:
        h, _, p = host.partition(":")
        try:
            return h, int(p)
        except ValueError:
            return h, OLLAMA_PORT
    return host, OLLAMA_PORT


async def _ollama_api_reachable(timeout: float = 0.75) -> bool:
    """Versione non-bloccante del check raggiungibilità Ollama."""
    def _check():
        host, port = _ollama_addr()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False
    return await asyncio.to_thread(_check)


def _resolve_ollama_executable() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    if sys.platform == "win32":
        local = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Programs",
            "Ollama",
            "ollama.exe",
        )
        if os.path.isfile(local):
            return local
    return None


def ensure_ollama_running(max_wait_sec: int = 45) -> None:
    """
    Se l'API Ollama non risponde, prova ad avviare `ollama serve` in background.
    Disabilita con MAYA_SKIP_OLLAMA_AUTOSTART=1 oppure se OLLAMA_HOST punta a un host remoto.
    """
    if os.environ.get("MAYA_SKIP_OLLAMA_AUTOSTART", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return

    host, _ = _ollama_addr()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return

    # Check sync reachable (using socket directly)
    def _check_sync():
        host, port = _ollama_addr()
        try:
            with socket.create_connection((host, port), timeout=0.75):
                return True
        except OSError:
            return False

    if _check_sync():
        return

    ollama_exe = _resolve_ollama_executable()
    if not ollama_exe:
        print(
            "[OLLAMA] Eseguibile non trovato. Installa Ollama da https://ollama.com "
            "oppure avvialo manualmente."
        )
        return

    print("[OLLAMA] Avvio del server locale in background...")
    popen_kw: dict = {
        "args": [ollama_exe, "serve"],
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        subprocess.Popen(**popen_kw)
    except OSError as e:
        print(f"[OLLAMA] Impossibile avviare ollama serve: {e}")
        return

    for i in range(max_wait_sec):
        if _check_sync():
            print("[OLLAMA] Server pronto.")
            return
        time.sleep(1)
        if i in (4, 14) and i > 0:
            print("[OLLAMA] Ancora in attesa del servizio...")

    print(
        "[OLLAMA] Timeout: il servizio non risponde. Avvia l'app Ollama o "
        "`ollama serve` da terminale, poi rilancia MAYA."
    )


def _pick_http_port(
    host: str = "127.0.0.1",
    *,
    max_attempts: int = 24,
) -> int:
    """
    Sceglie una porta TCP libera. Parte da MAYA_PORT (default 8000).
    Con MAYA_PORT_STRICT=1 usa solo quella e non prova altre (uvicorn fallirà se occupata).
    """
    first = int(os.environ.get("MAYA_PORT", "8000"))
    strict = os.environ.get("MAYA_PORT_STRICT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if strict:
        return first
    for port in range(first, first + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
            return port
        except OSError:
            continue
    return first


def print_banner():
    PEACH = "\033[38;5;203m"
    GRAY = "\033[90m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print(f"\n{PEACH}╭───────────────────────────────────────────────────╮")
    print(
        f"│ {RESET}✷ Welcome to the {BOLD}MAYA{RESET} research preview!            {PEACH}│"
    )
    print(f"╰───────────────────────────────────────────────────╯\n")

    print(f"{PEACH}{BOLD}")
    print(r" ███╗   ███╗  █████╗  ██╗   ██╗  █████╗ ")
    print(r" ████╗ ████║ ██╔══██╗ ╚██╗ ██╔╝ ██╔══██╗")
    print(r" ██╔████╔██║ ███████║  ╚████╔╝  ███████║")
    print(r" ██║╚██╔╝██║ ██╔══██║   ╚██╔╝   ██╔══██║")
    print(r" ██║ ╚═╝ ██║ ██║  ██║    ██║    ██║  ██║")
    print(r" ╚═╝     ╚═╝ ╚═╝  ╚═╝    ╚═╝    ╚═╝  ╚═╝")
    print(f"{RESET}")
    print(f" {GRAY}M.A.Y.A. - Multitask Advanced Yielding Assistant{RESET}")
    print(f" {GRAY}Sistema Agentico Locale - Offline First v1.0{RESET}\n")


from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from contextlib import asynccontextmanager


async def weather_broadcaster():
    """Trasmette il meteo alla dashboard ogni 30 minuti."""
    print("[BROADCASTER] Avvio loop meteo.")
    while True:
        try:
            weather_tool = agent.tool_manager.tools.get("weather")
            if weather_tool:
                # Wrap blocking requests call in a thread
                result = await asyncio.to_thread(weather_tool.execute, {})
                if result.get("status") == "ok":
                    user_log(f"Meteo aggiornato per {result['data']['location']}.")
                    await manager.broadcast({
                        "type": "weather",
                        "data": result.get("data")
                    })
                else:
                    await manager.broadcast({
                        "type": "weather",
                        "error": True
                    })
        except Exception as e:
            print(f"[BROADCASTER] Errore meteo: {e}")
            await manager.broadcast({
                "type": "weather",
                "error": True
            })
        await asyncio.sleep(1800)

async def news_broadcaster():
    """Trasmette le ultime notizie alla dashboard ogni 10 minuti."""
    print("[BROADCASTER] Avvio loop news.")
    while True:
        try:
            # Recupera il news_tool ogni volta dal tool_manager dell'agente globale
            news_tool = agent.tool_manager.tools.get("news")
            if news_tool:
                # Wrap blocking feedparser call in a thread
                result = await asyncio.to_thread(news_tool.execute, {"limit": 5})
                if result.get("status") == "ok":
                    user_log("Ultime notizie caricate.")
                    await manager.broadcast({
                        "type": "news",
                        "articles": result.get("news", [])
                    })
        except Exception as e:
            print(f"[BROADCASTER] Errore news: {e}")
        await asyncio.sleep(600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print_banner()
    print("\n[SYSTEM] Avvio dei sistemi MAYA...\n")
    # Imposta il loop prima di ogni altra cosa
    try:
        agent.loop = asyncio.get_running_loop()
    except RuntimeError:
        agent.loop = asyncio.get_event_loop()
    manager.loop = agent.loop
    # Segnala che il loop è pronto per VoiceManager
    voice_manager.set_loop_ready()

    await agent.initialize()
    
    # Inizializza PluginLoader e ProactiveManager
    plugins_dir = os.path.join(os.getcwd(), "plugins")
    os.makedirs(plugins_dir, exist_ok=True)
    
    plugin_loader = PluginLoader(agent.tool_manager, plugins_dir)
    plugin_loader.start()
    
    proactive_manager = ProactiveManager(agent.tool_manager, manager)
    asyncio.create_task(proactive_manager.start_loop())
    
    print("\n[SYSTEM] Sistemi operativi. Avvio interfaccia visiva...\n")
    # display.start()  # Disabilitato: conflitto stdout con console interattiva. Stato inviato via WebSocket

    dashboard_path = os.path.abspath("static/jarvis_dashboard.html")
    print(f"[MAYA] Apertura dashboard: {dashboard_path}")

    # Avvia la console e i broadcaster in background
    global _bg_tasks
    _bg_tasks = [
        asyncio.create_task(interactive_console()),
        asyncio.create_task(stats_broadcaster()),
        asyncio.create_task(spotify_broadcaster()),
        asyncio.create_task(news_broadcaster()),
        asyncio.create_task(weather_broadcaster())
    ]
    
    # Apri il browser con un piccolo ritardo (il server deve essere pronto)
    http_port = int(os.environ.get("MAYA_HTTP_PORT", "8000"))

    def _open_browser():
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
        def arduino_event_handler(event: dict):
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"type": "arduino_event", **event}),
                asyncio.get_event_loop()
            )
        arduino_tool.register_event_hook(arduino_event_handler)
    
    yield
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


app = FastAPI(lifespan=lifespan)
agent = AgentCore()
display = DisplayTool()
voice_manager = VoiceManager(agent, manager)

# Applica il filtro dei log della dashboard SUBITO dopo l'inizializzazione FastAPI
# Questo permette ai log di sistema di passare al terminale durante l'avvio
_log_filter_applied = False


@app.get("/")
async def get_dashboard():
    return FileResponse("static/jarvis_dashboard.html")


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global _log_filter_applied
    print(f"[WS] Nuova connessione da {websocket.client}")
    try:
        await manager.connect(websocket)
        print(f"[WS] Connessione accettata. Client attivi: {len(manager.active_connections)}")

        # Applica il filtro log al primo collegamento del client (una sola volta)
        if not _log_filter_applied:
            print("[WS] Applicazione filtro log alla dashboard.")
            setup_dashboard_log_filter(manager)
            _log_filter_applied = True

        print("[WS] Invio stato iniziale...")
        await broadcast_state()
        try:
            await websocket.send_json(voice_manager.voice_status_message())
        except Exception:
            pass

        while True:
            try:
                data = await websocket.receive_json()
                if data.get("type") == "command":
                    cmd = data.get("text", "")
                    if cmd:
                        # Invia la richiesta dell'utente alla dashboard tramite print (che passa dal filtro)
                        print(f"Richiesta: {cmd}")
                        asyncio.create_task(execute_and_broadcast(cmd))
                elif data.get("type") == "tool":
                    # Esecuzione diretta tool, bypassa LLM
                    action = data.get("action", {})
                    if action:
                        result = await agent.tool_manager.execute(action)
                        if action.get("tool") == "calendar" and "events" in result:
                            await manager.broadcast({
                                "type": "calendar_data",
                                "events": result.get("events", [])
                            })
                        else:
                            await manager.broadcast(
                                {
                                    "type": "log",
                                    "text": result.get("message", ""),
                                    "level": "ok",
                                }
                            )
                        await broadcast_state()
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


async def execute_and_broadcast(cmd: str):
    """
    Esegue il comando tramite agent.process() e trasmette la risposta in streaming.
    """

    # Callback per inviare il filler message al frontend quando elabora
    async def send_progress(msg: str):
        await manager.broadcast(
            {"type": "log", "text": f"🤖 MAYA: {msg}", "level": "info"}
        )

    # Streaming dei token
    full_reply = ""
    async for token in agent.process(cmd, progress_cb=send_progress):
        full_reply += token
        await manager.broadcast({
            "type": "stream",
            "token": token,
            "full_text": full_reply
        })

    # Stampa finale nel terminale per i log della dashboard (filtro esistente)
    # Rimuoviamo il prefisso MAYA > se vogliamo gestire lo streaming separatamente lato UI
    # ma lo lasciamo per compatibilità con il filtro log attuale se necessario.
    print(f"MAYA > {full_reply}")

    # Aggiorna lo stato del sistema (modelli, stats, ecc)
    await broadcast_state()


async def get_models_status():
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


async def broadcast_state():
    """
    Trasmette lo stato del sistema alla dashboard, includendo:
    - Stato dei modelli (online/offline)
    - Stato di Ollama
    - Informazioni di sistema
    """
    arduino_tool = agent.tool_manager.tools.get("arduino")
    models_status = await get_models_status()
    ollama_online = any(m.get("online", False) for m in models_status.values())
    
    _debug_reset_client = os.getenv("MAYA_DEBUG_RESET_CLIENT", "False").lower() == "true"

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
        "relay": (
            arduino_tool.sim_state.get("relay", "OFF")
            if isinstance(arduino_tool.sim_state.get("relay"), str)
            else ("ON" if arduino_tool.sim_state.get("relay") else "OFF")
        ).lower(),
        "servo": (
            arduino_tool.sim_state.get("servo", "CLOSED")
            if isinstance(arduino_tool.sim_state.get("servo"), str)
            else str(arduino_tool.sim_state.get("servo"))
        ).lower(),
        "system": {
            "model": MODELS.get("router", "llama3.2").upper(),
            "name": os.getenv("ASSISTANT_NAME", "MAYA"),
            "version": "2.0.1-dev",
            "reset_storage": _debug_reset_client,
        },
    }
    await manager.broadcast(state_payload)


async def stats_broadcaster():
    import psutil
    print("[BROADCASTER] Avvio loop statistiche.")

    # Warm-up: la prima chiamata con interval=None restituisce sempre 0.0
    psutil.cpu_percent(interval=None)
    await asyncio.sleep(0.1)

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
        await asyncio.sleep(0.33)


async def spotify_broadcaster():
    print("[BROADCASTER] Avvio loop spotify.")
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


async def interactive_console():
    """Legge i comandi dal terminale e li processa."""
    print("\n[MAYA] Sistema pronto. Digita un comando o 'exit' per uscire.\n")
    loop = asyncio.get_running_loop()
    while True:
        try:
            sys.stdout.write("MAYA > ")
            sys.stdout.flush()
            user_input = await loop.run_in_executor(None, sys.stdin.readline)
            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.lower() in ["exit", "quit", "esci"]:
                print("[MAYA] Spegnimento in corso...")
                os._exit(0)

            # Invia il comando dal terminale come se venisse dalla dashboard
            print(f"Richiesta: {user_input}")
            await execute_and_broadcast(user_input)

        except EOFError:
            # Terminale chiuso
            break
        except Exception as e:
            user_log(f"Errore comando: {e}", is_error=True)


if __name__ == "__main__":
    from instance_guard import (
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
                "[MAYA] È già attiva un'istanza (lock su 127.0.0.1:"
                f"{LOCK_PORT}).\n"
                "       Per chiuderla:  python main.py kill\n"
                "       Bypass (solo debug):  MAYA_SKIP_INSTANCE_GUARD=1\n"
            )
            sys.exit(1)
        install_signal_handlers(_instance_guard)

    _http_host = "127.0.0.1"
    _http_port = _pick_http_port(_http_host)
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
