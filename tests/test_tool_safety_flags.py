import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.self_healer import SelfHealer
from core.tool_manager import ToolManager


def test_network_tool_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NETWORK_TOOL_ENABLED", raising=False)

    manager = ToolManager()
    manager.initialize()

    assert "network" not in manager.tools


def test_network_tool_can_be_enabled_explicitly(monkeypatch):
    monkeypatch.setenv("NETWORK_TOOL_ENABLED", "true")

    manager = ToolManager()
    manager.initialize()

    assert "network" in manager.tools


def test_self_healer_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DISABLE_SELF_HEALER", raising=False)
    healer = SelfHealer(tool_manager=None)

    with patch.object(healer, "_attempt_fix", new_callable=AsyncMock) as attempt_fix:
        healer.record_error("weather", RuntimeError("boom"), __file__)

    assert attempt_fix.call_count == 0


def test_self_healer_disable_flag_blocks_auto_fix(monkeypatch):
    monkeypatch.setenv("DISABLE_SELF_HEALER", "true")
    healer = SelfHealer(tool_manager=None)

    with patch.object(healer, "_attempt_fix", new_callable=AsyncMock) as attempt_fix:
        for _ in range(3):
            healer.record_error("weather", RuntimeError("boom"), __file__)

    assert attempt_fix.call_count == 0
