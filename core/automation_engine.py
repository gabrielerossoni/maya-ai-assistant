"""Generic event-driven automation engine for M.A.Y.A."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Callable, Coroutine

from .context_manager import context

logger = logging.getLogger("maya.automation")


class Priority(IntEnum):
    LOW = 10
    NORMAL = 50
    HIGH = 80
    CRITICAL = 100


@dataclass
class Action:
    tool: str
    params: dict = field(default_factory=dict)
    delay: float = 0.0
    retry: int = 1
    timeout: float = 5.0
    background: bool = False

    def to_tool_action(self) -> dict:
        return {"tool": self.tool, **self.params}


def spotify(command: str, **kwargs) -> Action:
    return Action("spotify", {"command": command, **kwargs})


def background(action: Action) -> Action:
    action.background = True
    return action


def delayed_background(action: Action, delay: float) -> Action:
    action.delay = delay
    action.background = True
    return action


def timer_action(minutes: int, message: str) -> Action:
    return Action("timer", {"minutes": minutes, "message": message})


def weather_action(location: str | None = None) -> Action:
    return Action("weather", {"location": location})


def news_action(limit: int = 3) -> Action:
    return Action("news", {"limit": limit})


def calendar_action(act: str = "list") -> Action:
    return Action("calendar", {"action": act})


def display_action(layout: str, delay: float = 0.0, **params) -> Action:
    return Action("display", {"layout": layout, **params}, delay=delay)


@dataclass
class Condition:
    requirements: dict = field(default_factory=dict)

    def evaluate(self) -> bool:
        return not self.requirements or context.matches(self.requirements)


@dataclass
class Trigger:
    type: str
    time: str | None = None
    context: dict | None = None
    event_name: str | None = None


@dataclass
class Scene:
    name: str
    actions: list[Action] = field(default_factory=list)
    priority: Priority = Priority.NORMAL
    conditions: list[Condition] = field(default_factory=list)
    cooldown: float = 0.0
    exclusive: bool = False
    _last_run: float = field(default=0.0, init=False, repr=False)

    def can_run(self, ignore_cooldown: bool = False) -> bool:
        if not all(condition.evaluate() for condition in self.conditions):
            return False
        return ignore_cooldown or not self.cooldown or time.monotonic() - self._last_run >= self.cooldown

    def mark_run(self):
        self._last_run = time.monotonic()


@dataclass
class Automation:
    scene: Scene
    aliases: list[str] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    expires_at: float | None = None

    @property
    def name(self) -> str:
        return self.scene.name

    def is_valid(self) -> bool:
        return self.expires_at is None or time.monotonic() < self.expires_at

    @staticmethod
    def _normalize(text: str) -> str:
        text = unicodedata.normalize("NFKD", text.casefold())
        text = "".join(char for char in text if not unicodedata.combining(char))
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()

    def matches_input(self, text: str) -> bool:
        normalized = self._normalize(text)
        candidates = [self.name, *self.aliases]
        return any(
            re.search(rf"(?<!\w){re.escape(self._normalize(candidate))}(?!\w)", normalized) for candidate in candidates
        )


class EventBus:
    def __init__(self):
        self._handlers: dict[str, list[Callable[[dict], Coroutine]]] = {}

    def subscribe(self, event: str, handler: Callable[[dict], Coroutine]):
        self._handlers.setdefault(event, []).append(handler)

    def unsubscribe(self, event: str, handler: Callable):
        if event in self._handlers and handler in self._handlers[event]:
            self._handlers[event].remove(handler)

    async def publish(self, event: str, data: dict | None = None):
        for handler in list(self._handlers.get(event, [])):
            try:
                await handler(event, data or {})
            except TypeError:
                await handler(data or {})
            except Exception:
                logger.exception("Event handler failed: %s", event)


class AutomationEngine:
    def __init__(self, tool_manager=None, memory=None, socket_manager=None, voice_manager=None):
        self._tool_manager = tool_manager
        self.memory = memory
        self.socket_manager = socket_manager
        self.voice_manager = voice_manager
        self.bus = EventBus()
        self._automations: dict[str, Automation] = {}
        self._event_handlers: dict[str, list[tuple[str, Callable]]] = {}
        self._background_tasks: dict[str, list[asyncio.Task]] = {}
        self._event_log: list[dict] = []
        self._last_scene: str | None = None
        self._scheduler_task: asyncio.Task | None = None
        self.scheduler_interval = float(os.getenv("AUTOMATION_SCHEDULER_INTERVAL", "5"))
        self._last_trigger_minute: dict[str, str] = {}

    def register(self, automation: Automation):
        self.remove(automation.name)
        self._automations[automation.name] = automation
        self._wire_event_triggers(automation)

    def register_all(self, automations: list[Automation]):
        for automation in automations:
            self.register(automation)

    def add_temporary(self, automation: Automation, duration_seconds: float):
        automation.expires_at = time.monotonic() + duration_seconds
        self.register(automation)

    def remove(self, name: str):
        self._unwire_event_triggers(name)
        self._automations.pop(name, None)

    def _wire_event_triggers(self, automation: Automation):
        for trigger in automation.triggers:
            if trigger.type != "event" or not trigger.event_name:
                continue

            async def handler(_event="", _data=None, current=automation):
                await self.execute(current, source=f"event:{trigger.event_name}")

            self.bus.subscribe(trigger.event_name, handler)
            self._event_handlers.setdefault(automation.name, []).append((trigger.event_name, handler))

    def _unwire_event_triggers(self, automation_name: str):
        for event, handler in self._event_handlers.pop(automation_name, []):
            self.bus.unsubscribe(event, handler)

    def _purge_expired(self):
        for name, automation in list(self._automations.items()):
            if not automation.is_valid():
                self.remove(name)

    def resolve(self, user_input: str) -> Automation | None:
        self._purge_expired()
        matches = [automation for automation in self._automations.values() if automation.matches_input(user_input)]
        return max(matches, key=lambda item: item.scene.priority) if matches else None

    def resolve_by_name(self, name: str) -> Automation | None:
        self._purge_expired()
        return self._automations.get(name)

    def list_automations(self) -> list[str]:
        self._purge_expired()
        return list(self._automations)

    @staticmethod
    def _is_manual_source(source: str) -> bool:
        return source in {"manual", "voice", "dashboard", "websocket"}

    async def execute(self, automation: Automation, source: str = "manual") -> dict:
        scene = automation.scene
        if not scene.can_run(ignore_cooldown=self._is_manual_source(source)):
            reason = "conditions" if not all(condition.evaluate() for condition in scene.conditions) else "cooldown"
            return {"status": "skipped", "reason": reason, "scene": scene.name}
        foreground = [action for action in scene.actions if not action.background]
        background_actions = [action for action in scene.actions if action.background]
        results = await self.execute_actions(foreground, source=source)
        errors = [item for item in results if item["result"].get("status") == "error"]
        critical_errors = [item for item in errors if item["action"].tool in {"timer", "system"}]
        warnings = [
            {"action": item["action"].tool, "error": item["result"].get("message", "error")}
            for item in errors
            if item not in critical_errors
        ]
        if background_actions:
            task = asyncio.create_task(self._execute_background_actions(scene.name, background_actions))
            self._background_tasks.setdefault(scene.name, []).append(task)
        status = "partial" if critical_errors else "ok"
        scene.mark_run()
        self._last_scene = scene.name
        payload = {
            "status": status,
            "scene": scene.name,
            "results": [item["result"] for item in results],
            "errors": [
                {"action": item["action"].tool, "error": item["result"].get("message", "error")}
                for item in critical_errors
            ],
            "warnings": warnings,
            "conflicts": [],
            "message": f"Automazione {scene.name} eseguita.",
        }
        self._log_event({"event": "scene_executed", "source": source, **payload})
        await self.bus.publish("scene_executed", payload)
        return payload

    async def execute_by_name(self, name: str, source: str = "manual") -> dict:
        automation = self.resolve_by_name(name)
        return (
            await self.execute(automation, source)
            if automation
            else {"status": "error", "message": f"Automazione '{name}' non trovata"}
        )

    async def execute_actions(self, actions: list[Action], source: str = "manual") -> list[dict]:
        results = []
        for action in actions:
            if action.delay:
                await asyncio.sleep(action.delay)
            result = await self._execute_action_with_retry(action)
            results.append({"action": action, "result": result})
        return results

    async def _execute_action_with_retry(self, action: Action) -> dict:
        if not self._tool_manager:
            return {"status": "error", "message": "ToolManager non configurato"}
        last = {"status": "error", "message": "azione non eseguita"}
        for attempt in range(max(1, action.retry)):
            try:
                last = await asyncio.wait_for(
                    self._tool_manager.execute(action.to_tool_action()), timeout=action.timeout
                )
            except asyncio.TimeoutError:
                last = {"status": "error", "message": "timeout"}
            except Exception as exc:
                last = {"status": "error", "message": str(exc)}
            if last.get("status") != "error":
                break
            if attempt + 1 < max(1, action.retry):
                await asyncio.sleep(0.1 * (attempt + 1))
        return last

    async def _execute_background_actions(self, scene_name: str, actions: list[Action]):
        await self.execute_actions(actions, source=f"background:{scene_name}")

    def _cancel_background_tasks(self, scene_name: str | None = None):
        names = [scene_name] if scene_name else list(self._background_tasks)
        for name in names:
            for task in self._background_tasks.pop(name, []):
                if not task.done():
                    task.cancel()

    async def start_scheduler(self):
        if (
            self._scheduler_task
            and self._scheduler_task is not asyncio.current_task()
            and not self._scheduler_task.done()
        ):
            return
        self._scheduler_task = asyncio.current_task()
        while True:
            now = datetime.now()
            minute = now.strftime("%Y-%m-%d %H:%M")
            for automation in list(self._automations.values()):
                for trigger in automation.triggers:
                    key = f"{automation.name}:{trigger.type}"
                    if (
                        trigger.type == "time"
                        and trigger.time == now.strftime("%H:%M")
                        and self._last_trigger_minute.get(key) != minute
                    ):
                        self._last_trigger_minute[key] = minute
                        asyncio.create_task(self.execute(automation, source=f"scheduler:{trigger.time}"))
                    elif trigger.type == "context" and trigger.context and context.matches(trigger.context):
                        asyncio.create_task(self.execute(automation, source="context_trigger"))
            await asyncio.sleep(self.scheduler_interval)

    def _log_event(self, entry: dict):
        self._event_log.append({"time": datetime.now().isoformat(timespec="seconds"), **entry})
        self._event_log = self._event_log[-200:]

    def get_event_log(self, limit: int = 20) -> list[dict]:
        return self._event_log[-limit:]

    def get_last_scene(self) -> str | None:
        return self._last_scene

    async def clear_active_scene(self) -> dict:
        previous = self._last_scene
        self._cancel_background_tasks(previous)
        self._last_scene = None
        payload = {"status": "ok", "previous": previous, "message": "Automazione attiva terminata."}
        await self.bus.publish("scene_cleared", payload)
        return payload


def build_default_automations() -> list[Automation]:
    """Useful defaults that rely only on software/network services."""
    return [
        Automation(
            Scene(
                "buongiorno",
                [
                    display_action("news"),
                    news_action(5),
                    display_action("weather"),
                    weather_action(),
                    background(calendar_action()),
                ],
                Priority.HIGH,
                cooldown=60,
            ),
            aliases=["buon giorno", "morning"],
            triggers=[Trigger("time", time="07:00")],
        ),
        Automation(
            Scene("buonanotte", [spotify("pause"), background(calendar_action())], Priority.HIGH, cooldown=300),
            aliases=["buona notte", "notte", "vado a dormire", "vado a letto"],
            triggers=[Trigger("time", time="23:00")],
        ),
        Automation(
            Scene(
                "briefing",
                [display_action("weather"), weather_action(), news_action(3), background(calendar_action())],
                Priority.NORMAL,
                cooldown=1800,
            ),
            aliases=["briefing", "riepilogo giornata"],
        ),
        Automation(
            Scene("focus", [spotify("search", query="deep focus playlist")], Priority.NORMAL, cooldown=60),
            aliases=["deep work", "modalita focus"],
        ),
        Automation(
            Scene("vado fuori", [spotify("pause"), weather_action()], Priority.NORMAL, cooldown=30),
            aliases=["esco", "vado via"],
        ),
    ]


engine = AutomationEngine()
