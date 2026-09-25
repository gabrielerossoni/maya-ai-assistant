import os
import sys
from unittest.mock import AsyncMock, patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
