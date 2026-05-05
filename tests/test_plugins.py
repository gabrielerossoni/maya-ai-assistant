import sys
import os
import pytest
import asyncio
from unittest.mock import MagicMock, patch
from pathlib import Path

# Aggiungi la root del progetto al path per gli import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tool_manager import ToolManager
from plugin_loader import PluginLoader

class MockTool:
    def initialize(self):
        self.initialized = True
    def execute(self, action):
        return {"status": "ok", "message": "hello"}

@pytest.fixture
def tool_manager():
    tm = ToolManager()
    tm.initialize()
    return tm

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
