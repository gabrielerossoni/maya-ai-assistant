"""M.A.Y.A. application entry point."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import threading
import time
import webbrowser
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Header, HTTPException, WebSocket
from fastapi.staticfiles import StaticFiles

from core.agent_core import MODELS, AgentCore
from core.broadcasters import (
    interactive_console,
    news_broadcaster,
    spotify_broadcaster,
    stats_broadcaster,
    weather_broadcaster,
)
from core.context_manager import context as home_context
from core.ollama_manager import ensure_ollama_running
from core.proactive_manager import ProactiveManager
from core.routes import (
    _is_valid_dashboard_token,
    get_dashboard,
    get_manifest,
    get_news_live_streams,
    get_service_worker,
    health_check,
    websocket_endpoint,
)
from core.server_utils import pick_http_port
from core.voice_manager import VoiceManager
from core.websocket_manager import manager

_bg_tasks: list[asyncio.Task] = []
_shutdown_started = False


def _env_enabled(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes"}


def _authorize_shutdown(pid: int | None, token: str | None, header_token: str | None) -> bool:
    if pid is not None:
        if pid == os.getpid():
            return True
        raise HTTPException(status_code=403, detail="wrong_pid")
    if _is_valid_dashboard_token(token) or _is_valid_dashboard_token(header_token):
        return True
    raise HTTPException(status_code=403, detail="shutdown_not_authorized")


async def shutdown_services(reason: str = "shutdown"):
    global _shutdown_started
    if _shutdown_started:
        return
    _shutdown_started = True
    print(f"[SHUTDOWN] Arresto servizi ({reason})...")
    try:
        voice_manager.stop()
    except Exception as exc:
        print(f"[SHUTDOWN] Errore stop voce: {exc}")
    agent.automation_engine._cancel_background_tasks()
    for task in _bg_tasks:
        task.cancel()
    await asyncio.gather(*_bg_tasks, return_exceptions=True)
    for name, tool in agent.tool_manager.tools.items():
        close = getattr(tool, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                print(f"[SHUTDOWN] Errore chiusura {name}: {exc}")
    home_context.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bg_tasks
    agent.loop = asyncio.get_running_loop()
    manager.loop = agent.loop
    await agent.initialize()

    plugins_dir = os.path.join(os.path.dirname(__file__), "plugins")
    if _env_enabled("PLUGIN_LOADER_ENABLED") or _env_enabled("DEV_MODE"):
        from core.plugin_loader import PluginLoader

        PluginLoader(agent.tool_manager, plugins_dir).start()

    proactive = ProactiveManager(agent.tool_manager, manager, memory_manager=agent.memory, voice_manager=voice_manager)
    mqtt_tool = agent.tool_manager.tools.get("mqtt")
    if mqtt_tool and hasattr(mqtt_tool, "set_ws_manager"):
        mqtt_tool.set_ws_manager(manager, agent.loop)

    _bg_tasks = [
        asyncio.create_task(proactive.start_loop()),
        asyncio.create_task(interactive_console(agent, manager)),
        asyncio.create_task(stats_broadcaster(manager, voice_manager)),
        asyncio.create_task(spotify_broadcaster(agent, manager)),
        asyncio.create_task(news_broadcaster(agent, manager)),
        asyncio.create_task(weather_broadcaster(agent, manager)),
    ]

    async def on_scene(_event: str, data: dict):
        await manager.broadcast(
            {"type": "scene_executed", "scene": data.get("scene"), "status": data.get("status", "ok")}
        )

    agent.automation_engine.bus.subscribe("scene_executed", on_scene)
    try:
        voice_manager.start()
    except Exception as exc:
        print(f"[VOICE] Avvio non disponibile: {exc}")

    def open_browser():
        if os.getenv("MAYA_SKIP_BROWSER_OPEN") == "1":
            return
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{os.getenv('MAYA_HTTP_PORT', '8000')}/")

    threading.Thread(target=open_browser, daemon=True).start()
    try:
        yield
    finally:
        await shutdown_services("lifespan")


app = FastAPI(lifespan=lifespan)
agent = AgentCore()
agent.socket_manager = manager
voice_manager = VoiceManager(agent, manager)
agent.voice_manager = voice_manager


@app.get("/")
async def dashboard():
    return await get_dashboard()


@app.get("/sw.js")
async def service_worker():
    return await get_service_worker()


@app.get("/manifest.json")
async def manifest():
    return await get_manifest()


@app.get("/health")
async def health():
    return await health_check()


@app.get("/api/news/live-streams")
async def news_live_streams():
    return await get_news_live_streams()


@app.post("/shutdown")
async def shutdown(pid: int | None = None, token: str | None = None, x_maya_token: str | None = Header(default=None)):
    _authorize_shutdown(pid, token, x_maya_token)
    await shutdown_services("http")

    def stop_process():
        time.sleep(0.2)
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=stop_process, daemon=True).start()
    return {"status": "ok", "message": "shutdown avviato"}


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.websocket("/ws")
async def websocket(websocket: WebSocket):
    await websocket_endpoint(websocket, agent, manager, voice_manager, MODELS)


if __name__ == "__main__":
    from core.instance_guard import LOCK_PORT, InstanceGuard, install_signal_handlers, kill_existing, skip_guard

    if len(sys.argv) > 1 and sys.argv[1].lower() == "kill":
        raise SystemExit(0 if kill_existing() else 1)
    instance_guard = None
    if not skip_guard():
        instance_guard = InstanceGuard()
        if not instance_guard.acquire():
            print(f"[MAYA] Istanza gia attiva su 127.0.0.1:{LOCK_PORT}.")
            raise SystemExit(1)
        install_signal_handlers(instance_guard)
    host = "127.0.0.1"
    port = pick_http_port(host)
    os.environ["MAYA_HTTP_PORT"] = str(port)
    if instance_guard:
        instance_guard.update_port(port)
    threading.Thread(target=ensure_ollama_running, daemon=True).start()
    uvicorn.run("main:app", host=host, port=port, log_level="warning")
