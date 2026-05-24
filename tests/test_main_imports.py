"""
Smoke test: verifica che i moduli estratti da main.py importino correttamente.
Se questo test passa, il refactoring non ha rotto nulla a livello di import.
"""

import importlib
import os
import sys

# Assicura che la root del progetto sia nel path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def test_import_ollama_manager():
    mod = importlib.import_module("core.ollama_manager")
    assert hasattr(mod, "ensure_ollama_running")
    assert hasattr(mod, "_ollama_addr")
    assert hasattr(mod, "_ollama_api_reachable")
    assert hasattr(mod, "_resolve_ollama_executable")


def test_import_ngrok_manager():
    mod = importlib.import_module("core.ngrok_manager")
    assert hasattr(mod, "start_ngrok")


def test_import_server_utils():
    mod = importlib.import_module("core.server_utils")
    assert hasattr(mod, "pick_http_port")
    assert hasattr(mod, "print_banner")


def test_import_broadcasters():
    mod = importlib.import_module("core.broadcasters")
    assert hasattr(mod, "weather_broadcaster")
    assert hasattr(mod, "news_broadcaster")
    assert hasattr(mod, "stats_broadcaster")
    assert hasattr(mod, "spotify_broadcaster")
    assert hasattr(mod, "sensor_broadcaster")
    assert hasattr(mod, "broadcast_state")
    assert hasattr(mod, "interactive_console")
    assert hasattr(mod, "execute_and_broadcast")
    assert hasattr(mod, "broadcast_weather_update")


def test_import_routes():
    mod = importlib.import_module("core.routes")
    assert hasattr(mod, "get_dashboard")
    assert hasattr(mod, "get_service_worker")
    assert hasattr(mod, "get_manifest")
    assert hasattr(mod, "health_check")
    assert hasattr(mod, "websocket_endpoint")


def test_main_module_importable():
    """Verifica che main.py si importi senza errori (no execution di __main__)."""
    mod = importlib.import_module("main")
    assert hasattr(mod, "app")
    assert hasattr(mod, "agent")
    assert hasattr(mod, "voice_manager")
    assert hasattr(mod, "lifespan")
