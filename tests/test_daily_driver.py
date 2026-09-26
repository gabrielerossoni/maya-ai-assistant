from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent_core import AgentCore
from core.audit.logger import AuditLogger
from core.browser_agent import BrowserAgent, BrowserSafetyError
from core.fast_path import FastPathRouter
from core.memory.structured import StructuredMemory
from core.permissions.engine import PermissionEngine
from core.permissions.human_loop import HumanLoop
from core.scheduler import PersistentScheduler
from core.telegram_bot import TelegramBot


def test_fast_paths_parse_local_data_without_llm():
    operation, payload = FastPathRouter.structured_memory("ricordami domani alle 9 che scade la bolletta")
    assert operation == "reminder"
    assert payload["content"] == "scade la bolletta"
    assert FastPathRouter.structured_memory("dov'è il trapano?") == ("fact_lookup", {"query": "trapano"})
    assert FastPathRouter.calendar("mostra agenda")[0] == {"tool": "calendar", "action": "list"}


@pytest.mark.asyncio
async def test_scheduler_claims_persistent_reminder_once(tmp_path):
    memory = StructuredMemory(tmp_path / "memory.sqlite3")
    memory.initialize()
    reminder = memory.add_reminder("Bolletta", datetime.now(timezone.utc) - timedelta(seconds=1))
    delivered = []

    async def deliver(message):
        delivered.append(message)

    scheduler = PersistentScheduler(memory, deliver, interval=0)
    await scheduler.tick()
    await scheduler.tick()
    assert delivered == ["Promemoria: Bolletta"]
    assert memory.due_reminders() == []
    assert reminder["id"] > 0


@pytest.mark.asyncio
async def test_scheduler_retries_after_delivery_failure(tmp_path):
    memory = StructuredMemory(tmp_path / "memory.sqlite3")
    memory.initialize()
    memory.add_reminder("Bolletta", datetime.now(timezone.utc) - timedelta(seconds=1))
    attempts = 0

    async def deliver(_message):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("offline")

    scheduler = PersistentScheduler(memory, deliver)
    await scheduler.tick()
    assert len(memory.due_reminders()) == 1
    await scheduler.tick()
    assert attempts == 2 and memory.due_reminders() == []


def test_permission_engine_requires_confirmation_for_remote_side_effects():
    policy = PermissionEngine()
    assert policy.decide({"tool": "calendar", "action": "list"}).allowed
    decision = policy.decide({"tool": "mqtt", "target": "light", "value": 1})
    assert not decision.allowed and decision.requires_confirmation


def test_browser_requires_allowlist_and_rejects_private_networks():
    with pytest.raises(BrowserSafetyError):
        BrowserAgent().validate_url("https://example.com")
    with pytest.raises(BrowserSafetyError):
        BrowserAgent({"localhost"}).validate_url("https://localhost")


def test_confirmation_is_bound_to_requesting_user():
    loop = HumanLoop()
    token = loop.request({"tool": "mqtt"}, "user-a")
    assert loop.resolve(token, True, "user-b") is None


def test_telegram_restores_persisted_update_offset():
    agent = MagicMock()
    agent.structured_memory.get_preference.return_value = "42"
    bot = TelegramBot(agent)
    assert bot.offset == 42


def test_audit_events_return_structured_details(tmp_path):
    audit = AuditLogger(tmp_path / "audit.sqlite3")
    audit.record("checked", details={"ok": True})
    assert audit.list_recent()[0]["details"] == {"ok": True}


@pytest.mark.asyncio
async def test_note_reminder_fact_and_agenda_skip_llm():
    agent = AgentCore()
    agent.memory.add_turn = AsyncMock()
    agent.structured_memory = MagicMock()
    agent.structured_memory.add_reminder.return_value = {"content": "bolletta", "due_at": "2026-09-27T09:00:00+00:00"}
    agent.structured_memory.find_facts.return_value = [{"subject": "trapano", "value": "Marco"}]
    agent._call_llm = AsyncMock()
    agent.tool_manager.execute = AsyncMock(return_value={"status": "ok", "message": "Agenda locale"})

    for command in ("annota compra latte", "ricordami domani alle 9 bolletta", "dov'è il trapano?", "mostra agenda"):
        _ = "".join([chunk async for chunk in agent.process(command)])

    agent._call_llm.assert_not_called()


@pytest.mark.asyncio
async def test_telegram_calendar_delete_requires_confirmation():
    agent = AgentCore()
    agent.memory.add_turn = AsyncMock()
    agent.telegram_confirmation = AsyncMock()
    agent.tool_manager.execute = AsyncMock(return_value={"status": "ok", "message": "deleted"})
    response = "".join([chunk async for chunk in agent.process("cancella evento visita", source="telegram:42:99")])
    assert "conferma" in response.lower()
    agent.telegram_confirmation.assert_awaited_once()
    agent.tool_manager.execute.assert_not_awaited()


def test_fast_path_rejects_invalid_reminder_time():
    assert FastPathRouter.structured_memory("ricordami domani alle 99:99 bolletta") == (
        "invalid",
        {"message": "Orario promemoria non valido."},
    )
