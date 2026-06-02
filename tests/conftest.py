"""
conftest.py - Fixture condivise per la test suite Maya.
"""

import json
import os
import sys
import tempfile

import pytest

# Aggiungi la root del progetto al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Segnala che siamo in ambiente CI/test
os.environ["MAYA_CI"] = "true"
os.environ["OLLAMA_ENABLED"] = "false"
os.environ["SPOTIFY_ENABLED"] = "false"


@pytest.fixture
def tmp_data_dir(tmp_path):
    """Directory temporanea per file di stato (context, registry)."""
    return tmp_path


@pytest.fixture
def fresh_context(tmp_data_dir, monkeypatch):
    """ContextManager fresco, senza stato persistente su disco."""
    state_path = str(tmp_data_dir / "context_state.json")
    monkeypatch.setattr("core.context_manager._STATE_PATH", state_path)
    # Reset singleton
    from core.context_manager import ContextManager

    ContextManager._instance = None
    ctx = ContextManager()
    # Patch all module-level references to the global context singleton
    monkeypatch.setattr("core.context_manager.context", ctx)
    monkeypatch.setattr("core.automation_engine.context", ctx)
    yield ctx
    ContextManager._instance = None


@pytest.fixture
def fresh_registry(tmp_data_dir, monkeypatch):
    """DeviceRegistry fresco, senza stato persistente."""
    reg_path = str(tmp_data_dir / "device_registry.json")
    monkeypatch.setattr("core.device_registry._REGISTRY_PATH", reg_path)
    from core.device_registry import DeviceRegistry

    DeviceRegistry._instance = None
    reg = DeviceRegistry()
    monkeypatch.setattr("core.device_registry.registry", reg)
    monkeypatch.setattr("core.automation_engine.registry", reg)
    yield reg
    DeviceRegistry._instance = None


@pytest.fixture
def mock_tool_manager():
    """ToolManager mock che registra le azioni eseguite."""
    from unittest.mock import AsyncMock, MagicMock

    tm = MagicMock()
    tm.execute = AsyncMock(return_value={"status": "ok", "message": "mock"})
    return tm
