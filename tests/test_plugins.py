import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Aggiungi la root del progetto al path per gli import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.plugin_loader import PluginLoader
from tools.code_generator_tool import CodeGeneratorTool


class MockTool:
    def initialize(self):
        self.initialized = True

    def execute(self, action):
        return {"status": "ok", "message": "hello"}


class SimpleToolManager:
    def __init__(self):
        self.tools = {}

    def register_tool(self, name, tool_instance):
        if hasattr(tool_instance, "initialize"):
            tool_instance.initialize()
        self.tools[name] = tool_instance
        return True

    def unregister_tool(self, name):
        self.tools.pop(name, None)
        return True


@pytest.fixture
def tool_manager():
    return SimpleToolManager()


def test_register_unregister_tool(tool_manager):
    mock_tool = MockTool()
    tool_manager.register_tool("mock", mock_tool)
    assert "mock" in tool_manager.tools

    tool_manager.unregister_tool("mock")
    assert "mock" not in tool_manager.tools


def test_hot_reload_logic(tool_manager, tmp_path):
    # Crea una cartella plugins temporanea
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()

    loader = PluginLoader(tool_manager, str(plugins_dir))

    # Crea un nuovo file tool
    tool_code = """
class TestTool:
    def initialize(self):
        pass
    def execute(self, action):
        return {"status": "ok", "message": "plugin_works"}
"""
    tool_file = plugins_dir / "test_tool.py"
    tool_file.write_text(tool_code)

    # Forza il caricamento manuale per il test (senza attendere watchdog)
    loader.event_handler._load_plugin(tool_file)

    assert "test" in tool_manager.tools
    result = tool_manager.tools["test"].execute({})
    assert result["message"] == "plugin_works"


@pytest.mark.asyncio
async def test_code_generator_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    tool = CodeGeneratorTool()
    tool.initialize()

    result = await tool.execute(
        {
            "filename": "../escape_tool.py",
            "code": "class EscapeTool:\n    def execute(self, action):\n        return {'status': 'ok'}\n",
        }
    )

    assert result["status"] == "error"
    assert not (tmp_path / "escape_tool.py").exists()
