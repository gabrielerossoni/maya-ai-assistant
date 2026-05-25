"""
test_automation_engine.py - Test asincroni per AutomationEngine, Scene, EventBus.

Copre: registrazione, resolve, execute, event bus, conflict detection,
cooldown, condizioni, automazioni temporanee.
"""

import asyncio
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.automation_engine import (
    Action,
    Automation,
    AutomationEngine,
    Condition,
    EventBus,
    Priority,
    Scene,
    Trigger,
    arduino,
    build_default_automations,
    spotify,
)

# ── Fixture locali ────────────────────────────────────────────────────────────


@pytest.fixture
def engine(mock_tool_manager, fresh_context, fresh_registry):
    """AutomationEngine pulito con ToolManager mock."""
    eng = AutomationEngine(tool_manager=mock_tool_manager)
    return eng


def _simple_automation(
    name="test_scene", aliases=None, priority=Priority.NORMAL, cooldown=0, conditions=None, exclusive=False
) -> Automation:
    """Helper per creare un'automazione minimale."""
    return Automation(
        scene=Scene(
            name=name,
            priority=priority,
            cooldown=cooldown,
            exclusive=exclusive,
            conditions=conditions or [],
            actions=[
                Action(tool="arduino", params={"op": "SET", "target": "light", "value": 1}),
            ],
        ),
        aliases=aliases or [],
    )


# ── Test registrazione ────────────────────────────────────────────────────────


class TestRegistration:
    def test_register_single(self, engine):
        auto = _simple_automation("luce on")
        engine.register(auto)
        assert "luce on" in engine.list_automations()

    def test_register_all(self, engine):
        autos = [_simple_automation(f"scene_{i}") for i in range(5)]
        engine.register_all(autos)
        assert len(engine.list_automations()) == 5

    def test_remove(self, engine):
        engine.register(_simple_automation("da_rimuovere"))
        engine.remove("da_rimuovere")
        assert "da_rimuovere" not in engine.list_automations()

    def test_temporary_automation_expires(self, engine):
        auto = _simple_automation("temporanea")
        engine.add_temporary(auto, duration_seconds=0.01)
        assert "temporanea" in engine.list_automations()
        time.sleep(0.02)
        assert "temporanea" not in engine.list_automations()


# ── Test resolve ──────────────────────────────────────────────────────────────


class TestResolve:
    def test_resolve_by_name(self, engine):
        engine.register(_simple_automation("buonanotte", aliases=["notte"]))
        result = engine.resolve("buonanotte")
        assert result is not None
        assert result.name == "buonanotte"

    def test_resolve_by_alias(self, engine):
        engine.register(_simple_automation("buonanotte", aliases=["notte", "vado a dormire"]))
        result = engine.resolve("è ora, notte!")
        assert result is not None
        assert result.name == "buonanotte"

    def test_resolve_no_match(self, engine):
        engine.register(_simple_automation("buonanotte"))
        result = engine.resolve("che tempo fa domani?")
        assert result is None

    def test_resolve_priority_ordering(self, engine):
        engine.register(_simple_automation("low_scene", aliases=["test"], priority=Priority.LOW))
        engine.register(_simple_automation("high_scene", aliases=["test"], priority=Priority.HIGH))
        result = engine.resolve("fai il test")
        assert result.name == "high_scene"


# ── Test execute ──────────────────────────────────────────────────────────────


class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_ok(self, engine, mock_tool_manager):
        auto = _simple_automation("scena_ok")
        engine.register(auto)
        result = await engine.execute(auto, source="test")
        assert result["status"] == "ok"
        mock_tool_manager.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_by_name(self, engine, mock_tool_manager):
        engine.register(_simple_automation("scena_nome"))
        result = await engine.execute_by_name("scena_nome", source="test")
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_execute_by_name_not_found(self, engine):
        result = await engine.execute_by_name("non_esiste")
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_execute_with_action_error(self, engine, mock_tool_manager):
        mock_tool_manager.execute = AsyncMock(return_value={"status": "error", "message": "device offline"})
        auto = _simple_automation("scena_errore")
        engine.register(auto)
        result = await engine.execute(auto)
        assert result["status"] == "partial"
        assert len(result["errors"]) == 1

    @pytest.mark.asyncio
    async def test_execute_respects_cooldown(self, engine, mock_tool_manager):
        auto = _simple_automation("scena_cooldown", cooldown=9999)
        engine.register(auto)
        r1 = await engine.execute(auto)
        assert r1["status"] == "ok"
        r2 = await engine.execute(auto)
        assert r2["status"] == "skipped"
        assert r2["reason"] == "cooldown"

    @pytest.mark.asyncio
    async def test_execute_action_timeout(self, engine, mock_tool_manager):
        async def slow_execute(_):
            await asyncio.sleep(10)

        mock_tool_manager.execute = slow_execute

        auto = Automation(
            scene=Scene(
                name="timeout_scene",
                actions=[Action(tool="arduino", params={"op": "SET"}, timeout=0.05)],
            ),
        )
        engine.register(auto)
        result = await engine.execute(auto)
        assert result["status"] == "partial"

    @pytest.mark.asyncio
    async def test_execute_multi_action_sequence(self, engine, mock_tool_manager):
        auto = Automation(
            scene=Scene(
                name="multi",
                actions=[
                    Action(tool="arduino", params={"op": "SET", "target": "light"}),
                    Action(tool="spotify", params={"command": "play"}),
                    Action(tool="weather", params={"location": "Milano"}),
                ],
            ),
        )
        engine.register(auto)
        result = await engine.execute(auto)
        assert result["status"] == "ok"
        assert mock_tool_manager.execute.call_count == 3


# ── Test condizioni ───────────────────────────────────────────────────────────


class TestConditions:
    @pytest.mark.asyncio
    async def test_condition_blocks_execution(self, engine, fresh_context, monkeypatch):
        import core.automation_engine as _ae

        fresh_context.set("time_slot", "morning")
        monkeypatch.setattr(_ae, "context", fresh_context)
        auto = _simple_automation(
            "solo_notte",
            conditions=[Condition({"time_slot": "night"})],
        )
        engine.register(auto)
        with patch("core.automation_engine.context", fresh_context):
            result = await engine.execute(auto)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_condition_allows_execution(self, engine, mock_tool_manager, fresh_context):
        fresh_context.set("presence", "home")
        with patch.object(
            type(fresh_context), "_compute_time_slot", return_value=fresh_context.get("time_slot", "afternoon")
        ):
            auto = _simple_automation(
                "quando_casa",
                conditions=[Condition({"presence": "home"})],
            )
            engine.register(auto)
            result = await engine.execute(auto)
            assert result["status"] == "ok"


# ── Test EventBus ─────────────────────────────────────────────────────────────


class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_subscribe(self):
        bus = EventBus()
        received = []

        async def handler(event, data):
            received.append((event, data))

        bus.subscribe("test_event", handler)
        await bus.publish("test_event", {"key": "value"})

        assert len(received) == 1
        assert received[0] == ("test_event", {"key": "value"})

    @pytest.mark.asyncio
    async def test_wildcard_subscriber(self):
        bus = EventBus()
        received = []

        async def handler(event, data):
            received.append(event)

        bus.subscribe("*", handler)
        await bus.publish("event_a")
        await bus.publish("event_b")

        assert received == ["event_a", "event_b"]

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        bus = EventBus()
        received = []

        async def handler(event, data):
            received.append(event)

        bus.subscribe("ev", handler)
        bus.unsubscribe("ev", handler)
        await bus.publish("ev")

        assert received == []

    @pytest.mark.asyncio
    async def test_handler_exception_doesnt_break_bus(self):
        bus = EventBus()
        received = []

        async def bad_handler(event, data):
            raise RuntimeError("boom")

        async def good_handler(event, data):
            received.append(event)

        bus.subscribe("ev", bad_handler)
        bus.subscribe("ev", good_handler)
        await bus.publish("ev")

        assert received == ["ev"]

    @pytest.mark.asyncio
    async def test_sync_handler(self):
        bus = EventBus()
        received = []

        def sync_handler(event, data):
            received.append(event)

        bus.subscribe("ev", sync_handler)
        await bus.publish("ev")

        assert received == ["ev"]


# ── Test scene_executed event ─────────────────────────────────────────────────


class TestEngineEvents:
    @pytest.mark.asyncio
    async def test_scene_executed_event_published(self, engine, mock_tool_manager):
        received = []

        async def on_scene(event, data):
            received.append(data)

        engine.bus.subscribe("scene_executed", on_scene)
        auto = _simple_automation("evento_scene")
        engine.register(auto)
        await engine.execute(auto)

        assert len(received) == 1
        assert received[0]["scene"] == "evento_scene"
        assert received[0]["status"] == "ok"

    def test_event_log_capped(self, engine):
        for i in range(250):
            engine._log_event({"i": i})
        assert len(engine.get_event_log(limit=999)) <= 200


# ── Test build_default_automations ────────────────────────────────────────────


class TestDefaults:
    def test_defaults_build(self, fresh_context, fresh_registry):
        autos = build_default_automations()
        assert len(autos) >= 12
        names = [a.name for a in autos]
        assert "buonanotte" in names
        assert "buongiorno" in names
        assert "allarme" in names

    def test_defaults_register_without_error(self, engine, fresh_context, fresh_registry):
        autos = build_default_automations()
        engine.register_all(autos)
        assert len(engine.list_automations()) == len(autos)
