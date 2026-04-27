"""
MAYA - Sistema AI Agentico Locale
Punto di ingresso principale
"""

import asyncio
import sys
import os
import webbrowser
from agent_core import AgentCore
from tools.display_tool import DisplayTool


def print_banner():
    # Colore arancio/pesca (simile a Claude): ANSI 209 o 203
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
from websocket_manager import manager
from contextlib import asynccontextmanager

app = FastAPI()
agent = AgentCore()
display = DisplayTool()


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
    await manager.connect(websocket)
    await broadcast_state()  # Invia lo stato iniziale
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "command":
                cmd = data.get("text", "")
                if cmd:
                    # Log dettagliato solo in console
                    print(f"[WEB] {cmd}")
                    asyncio.create_task(execute_and_broadcast(cmd))
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def execute_and_broadcast(cmd: str):
    async def progress_cb(msg: str):
        await manager.broadcast({"type": "log", "text": msg, "level": "info"})

    response = await agent.process(cmd, progress_cb=progress_cb)
    await manager.broadcast({"type": "log", "text": response, "level": "ok"})
    await broadcast_state()


async def broadcast_state():
    """Invia lo stato attuale (memoria, tools) alla dashboard."""
    arduino_tool = None
    if "arduino" in agent.tool_manager.tools:
        arduino_tool = agent.tool_manager.tools["arduino"]

    # Estraiamo l'ultimo LLM ms se salvato (simuliamo per ora se non c'è)
    state_payload = {
        "type": "state",
        "cmdCount": len(agent.memory.turns) // 2,
        "memTurns": len(agent.memory.turns),
        "led": (
            arduino_tool.sim_state.get("light", "OFF").lower()
            if arduino_tool
            else "off"
        ),
        "relay": (
            arduino_tool.sim_state.get("relay", "OFF").lower()
            if arduino_tool
            else "off"
        ),
        "servo": (
            arduino_tool.sim_state.get("servo", "CLOSED").lower()
            if arduino_tool
            else "closed"
        ),
    }
    await manager.broadcast(state_payload)


async def stats_broadcaster():
    """Invia statistiche reali del sistema (CPU e RAM)."""
    import psutil

    while True:
        try:
            # CPU Load (Neural Load)
            cpu_load = psutil.cpu_percent(interval=None)
            # RAM Usage
            memory = psutil.virtual_memory()

            stats = {
                "type": "stats",
                "neural_load": cpu_load,
                "memory": memory.percent,
                "ram_used_gb": round(memory.used / (1024**3), 1),
                "ram_total_gb": 24,  # Impostato fisso come richiesto dall'utente
                "uptime": "Online",
            }
            await manager.broadcast(stats)
        except:
            pass
        await asyncio.sleep(0.33)


async def interactive_console():
    print("\n[MAYA] Sistema pronto. Digita un comando o 'exit' per uscire.")
    loop = asyncio.get_running_loop()
    while True:
        try:
            user_input = await loop.run_in_executor(None, sys.stdin.readline)
            user_input = user_input.strip()
            if not user_input:
                continue
            user_prompt = "MAYA > "
            sys.stdout.write(user_prompt)
            sys.stdout.flush()
            if user_input.lower() in ["exit", "quit", "esci"]:
                print("[MAYA] Spegnimento in corso...")
                os._exit(0)

            # Log dettagliato solo in console
            print(f"[TERM] {user_input}")

            async def progress_cb(msg: str):
                print(f"MAYA > {msg}")
                await manager.broadcast({"type": "log", "text": msg, "level": "info"})

            response = await agent.process(user_input, progress_cb=progress_cb)
            print(f"\nMAYA > {response}\n")
            await manager.broadcast({"type": "log", "text": response, "level": "ok"})
            await broadcast_state()

        except Exception as e:
            print(f"[ERRORE] {e}")


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, log_level="warning")
