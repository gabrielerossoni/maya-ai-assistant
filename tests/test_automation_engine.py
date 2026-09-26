from unittest.mock import AsyncMock

import pytest

from core.automation_engine import (
    Action,
    Automation,
    AutomationEngine,
    EventBus,
    Priority,
    Scene,
    Trigger,
    build_default_automations,
)


def test_registration_and_resolution_prefers_priority():
    engine = AutomationEngine()
    low = Automation(Scene("low", priority=Priority.LOW), aliases=["test"])
    high = Automation(Scene("high", priority=Priority.HIGH), aliases=["test"])
    engine.register_all([low, high])
    assert engine.resolve("fai il test").name == "high"


@pytest.mark.asyncio
async def test_execute_generic_action():
    manager = AsyncMock()
    manager.execute.return_value = {"status": "ok", "message": "done"}
    engine = AutomationEngine(tool_manager=manager)
    automation = Automation(Scene("meteo", actions=[Action("weather", {"location": "Roma"})]))
    result = await engine.execute(automation)
    assert result["status"] == "ok"
    manager.execute.assert_awaited_once_with({"tool": "weather", "location": "Roma"})


@pytest.mark.asyncio
async def test_event_bus_dispatches_registered_automation():
    manager = AsyncMock()
    manager.execute.return_value = {"status": "ok"}
    engine = AutomationEngine(tool_manager=manager)
    automation = Automation(
        Scene("sync", actions=[Action("calendar", {"action": "list"})]),
        triggers=[Trigger("event", event_name="refresh")],
    )
    engine.register(automation)
    await engine.bus.publish("refresh", {})
    manager.execute.assert_awaited_once()


def test_defaults_are_software_only():
    automations = build_default_automations()
    assert automations
    assert all(
        action.tool in {"calendar", "display", "news", "spotify", "weather", "timer"}
        for automation in automations
        for action in automation.scene.actions
    )
