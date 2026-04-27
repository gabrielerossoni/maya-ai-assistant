"""
MAYA - Sistema AI Agentico Locale
Punto di ingresso principale
"""

import asyncio
import sys
import os
import webbrowser
import ollama
from agent_core import AgentCore, MODELS
from tools.display_tool import DisplayTool
from log_utils import setup_dashboard_log_filter

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
    print(f"│ {RESET}✷ Welcome to the {BOLD}MAYA{RESET} research preview!            {PEACH}│")
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
from websocket_manager import manager
from contextlib import asynccontextmanager

app = FastAPI()
agent = AgentCore()
display = DisplayTool()

# Applica il filtro dei log della dashboard SUBITO dopo l'inizializzazione FastAPI
# Questo permette ai log di sistema di passare al terminale durante l'avvio
_log_filter_applied = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print_banner()
    print("\n[SYSTEM] Avvio dei sistemi MAYA...\n")
    await agent.initialize()
    print("\n[SYSTEM] Sistemi operativi. Avvio interfaccia visiva...\n")
    display.start()

    dashboard_path = os.path.abspath("static/jarvis_dashboard.html")
    print(f"[MAYA] Apertura dashboard: {dashboard_path}")
    webbrowser.open(f"http://127.0.0.1:8000")

    # Avvia la console e i broadcaster in background
    asyncio.create_task(interactive_console())
    asyncio.create_task(stats_broadcaster())
    yield
    # Shutdown
    display.stop()

app.router.lifespan_context = lifespan

@app.get("/")
async def get_dashboard():
    return FileResponse("static/jarvis_dashboard.html")

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global _log_filter_applied
    await manager.connect(websocket)
    
    # Applica il filtro log al primo collegamento del client (una sola volta)
    if not _log_filter_applied:
        setup_dashboard_log_filter(manager)
        _log_filter_applied = True
    
    # Segnale di connessione riuscita
    await manager.broadcast({"type": "log", "text": "Nucleo Maya Connesso", "level": "ok"})
    await broadcast_state()
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "command":
                cmd = data.get("text", "")
                if cmd:
                    # Invia la richiesta dell'utente alla dashboard tramite print (che passa dal filtro)
                    print(f"Richiesta: {cmd}")
                    asyncio.create_task(execute_and_broadcast(cmd))
    except WebSocketDisconnect:
        manager.disconnect(websocket)

async def execute_and_broadcast(cmd: str):
    """
    Esegue il comando tramite agent.process() e trasmette la risposta.
    La risposta passa attraverso il filtro log che la invia alla dashboard.
    """
    response = await agent.process(cmd)
    
    # Stampa nel terminale con il prefisso "MAYA >" che viene catturato dal filtro
    print(f"MAYA > {response}")
    
    # Aggiorna lo stato del sistema (modelli, stats, ecc)
    await broadcast_state()

async def get_models_status():
    """
    Controlla lo stato di tutti i modelli configurati su Ollama.
    Ritorna un dizionario con il nome del modello e il suo stato (online/offline).
    """
    try:
        client = ollama.AsyncClient()
        local_models = await client.list()
        downloaded = [m.get('name', '') for m in local_models.get('models', [])]
        
        status = {}
        for key, name in MODELS.items():
            # Controlla se il modello esatto o una variante è disponibile
            is_ok = any(name in d or d in name for d in downloaded)
            status[key] = {
                "name": name,
                "online": is_ok,
                "id": key
            }
        return status
    except Exception as e:
        print(f"[MONITOR] Errore nel controllo modelli: {e}")
        # Ritorna tutti i modelli come offline se c'è un errore
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

    state_payload = {
        "type": "state",
        "cmdCount": len(agent.memory.turns) // 2 if hasattr(agent, 'memory') else 0,
        "memTurns": len(agent.memory.turns) if hasattr(agent, 'memory') else 0,
        "ollama": "ONLINE" if ollama_online else "OFFLINE",
        "models": models_status,
        "led": arduino_tool.sim_state.get("light", "OFF").lower() if arduino_tool else "off",
        "relay": arduino_tool.sim_state.get("relay", "OFF").lower() if arduino_tool else "off",
        "servo": arduino_tool.sim_state.get("servo", "CLOSED").lower() if arduino_tool else "closed",
        "system": {
            "model": MODELS.get("ultra-fast", "llama3.2").upper(),
            "name": os.getenv("ASSISTANT_NAME", "MAYA"),
            "version": "1.2.0"
        }
    }
    await manager.broadcast(state_payload)

async def stats_broadcaster():
    import psutil
    while True:
        try:
            cpu_load = psutil.cpu_percent(interval=None)
            memory = psutil.virtual_memory()
            stats = {
                "type": "stats",
                "neural_load": cpu_load,
                "memory": memory.percent,
                "ram_used_gb": round(memory.used / (1024**3), 1),
                "ram_total_gb": 24,
                "uptime": "Online",
            }
            await manager.broadcast(stats)
        except:
            pass
        await asyncio.sleep(0.33)

async def interactive_console():
    """Legge i comandi dal terminale e li processa."""
    print("\n[MAYA] Sistema pronto. Digita un comando o 'exit' per uscire.\n")
    loop = asyncio.get_running_loop()
    while True:
        try:
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
            print(f"[ERRORE] {e}")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="warning")
