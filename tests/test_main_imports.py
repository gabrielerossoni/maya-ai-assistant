"""
Smoke test: verifica che i moduli estratti da main.py importino correttamente.
Se questo test passa, il refactoring non ha rotto nulla a livello di import.
"""

import importlib
import os
import sys

import pytest

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
    assert hasattr(mod, "get_news_live_streams")
    assert hasattr(mod, "websocket_endpoint")


def test_news_live_default_groups_exclude_bbc_premiere_channel():
    mod = importlib.import_module("core.routes")
    sources = [stream["src"] for group in mod._NEWS_LIVE_GROUPS for stream in group]

    assert "UC16niRr50-MSBwiO3YDb3RA" not in sources
    assert "UCoMdktPbSTixAyNGwb-UYkQ" not in sources
    assert "UCknLrEdhRCp1aegoMqRaCZg" not in sources
    assert "UCSrZ3UV4jOidv8ppoVuvW9Q" in sources
    assert "UC7fWeaHhqgM4Ry-RMpM2YYw" in sources


@pytest.mark.asyncio
async def test_news_live_streams_fallback_when_primary_offline():
    mod = importlib.import_module("core.routes")
    calls = []

    async def checker(_client, channel_id):
        calls.append(channel_id)
        return channel_id == "fallback-live"

    streams = await mod._select_news_live_streams(
        groups=[
            [
                {"src": "primary-offline", "label": "PRIMARY"},
                {"src": "fallback-live", "label": "FALLBACK"},
            ]
        ],
        checker=checker,
    )

    assert calls == ["primary-offline", "fallback-live"]
    assert streams == [{"src": "fallback-live", "label": "FALLBACK", "fallback": True}]


@pytest.mark.asyncio
async def test_news_live_streams_uses_non_primary_when_all_unverified():
    mod = importlib.import_module("core.routes")

    async def checker(_client, _channel_id):
        return False

    streams = await mod._select_news_live_streams(
        groups=[
            [
                {"src": "bbc-upcoming", "label": "BBC NEWS"},
                {"src": "fallback-live", "label": "FALLBACK"},
            ]
        ],
        checker=checker,
    )

    assert streams == [{"src": "fallback-live", "label": "FALLBACK", "fallback": True, "unchecked": True}]


@pytest.mark.asyncio
async def test_news_live_streams_are_unique_across_slots():
    mod = importlib.import_module("core.routes")
    live = {"a", "b", "c"}

    async def checker(_client, channel_id):
        return channel_id in live

    streams = await mod._select_news_live_streams(
        groups=[
            [
                {"src": "a", "label": "A"},
                {"src": "b", "label": "B"},
            ],
            [
                {"src": "a", "label": "A"},
                {"src": "b", "label": "B"},
                {"src": "c", "label": "C"},
            ],
            [
                {"src": "b", "label": "B"},
                {"src": "c", "label": "C"},
            ],
        ],
        checker=checker,
    )

    assert [stream["src"] for stream in streams] == ["a", "b", "c"]
    assert len({stream["src"] for stream in streams}) == len(streams)


@pytest.mark.asyncio
async def test_youtube_live_channel_rejects_scheduled_prelive():
    mod = importlib.import_module("core.routes")

    class Response:
        def __init__(self, status_code, text=""):
            self.status_code = status_code
            self.text = text

    class Client:
        async def get(self, url):
            if "oembed" in url:
                return Response(200)
            return Response(200, '{"scheduledStartTime":"2026-06-04T20:00:00Z","isUpcoming":true}')

    assert await mod._youtube_live_channel_available(Client(), "bbc") is False


@pytest.mark.asyncio
async def test_youtube_live_channel_accepts_real_live_marker():
    mod = importlib.import_module("core.routes")

    class Response:
        def __init__(self, status_code, text=""):
            self.status_code = status_code
            self.text = text

    class Client:
        async def get(self, url):
            if "oembed" in url:
                return Response(200)
            return Response(200, '{"isLiveNow":true}')

    assert await mod._youtube_live_channel_available(Client(), "live") is True


def test_main_module_importable():
    """Verifica che main.py si importi senza errori (no execution di __main__)."""
    mod = importlib.import_module("main")
    assert hasattr(mod, "app")
    assert hasattr(mod, "agent")
    assert hasattr(mod, "voice_manager")
    assert hasattr(mod, "lifespan")
