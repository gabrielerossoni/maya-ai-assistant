import pytest

from core.tool_manager import ToolManager


class AsyncOnlyTool:
    def execute(self, _action):
        raise AssertionError("sync execute should not be called")

    async def execute_async(self, action):
        return {"status": "ok", "message": action["value"]}


@pytest.mark.asyncio
async def test_tool_manager_prefers_execute_async():
    manager = ToolManager()
    manager.tools = {"async_tool": AsyncOnlyTool()}

    result = await manager.execute({"tool": "async_tool", "value": "done"})

    assert result == {"status": "ok", "message": "done"}
