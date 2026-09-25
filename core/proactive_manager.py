"""Low-noise proactive checks for system, calendar, weather, and news."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta

import psutil


class BaseChecker:
    def __init__(self, name: str):
        self.name = name

    async def check(self):
        raise NotImplementedError


class SysMonitorChecker(BaseChecker):
    def __init__(self, cpu_threshold=80, ram_threshold=85):
        super().__init__("System Monitor")
        self.cpu_threshold = cpu_threshold
        self.ram_threshold = ram_threshold

    async def check(self):
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        if cpu > self.cpu_threshold:
            return f"Utilizzo CPU elevato: {cpu}%."
        if ram > self.ram_threshold:
            return f"Utilizzo RAM elevato: {ram}%."
        return None


class CalendarChecker(BaseChecker):
    def __init__(self, calendar_tool):
        super().__init__("Calendar")
        self.calendar_tool = calendar_tool
        self.last_notified_event = None

    async def check(self):
        result = self.calendar_tool.execute({"action": "next"})
        if result.get("status") != "ok" or "event" not in result:
            return None
        event = result["event"]
        difference = datetime.strptime(event["time"], "%Y-%m-%d %H:%M") - datetime.now()
        if timedelta(0) < difference < timedelta(minutes=15) and self.last_notified_event != event["id"]:
            self.last_notified_event = event["id"]
            return f"L'evento '{event['title']}' inizia tra poco ({event['time']})."
        return None


class CalendarSyncChecker(BaseChecker):
    def __init__(self, calendar_tool):
        super().__init__("Calendar Sync")
        self.calendar_tool = calendar_tool

    async def check(self):
        synced = self.calendar_tool.sync_local_to_google()
        return f"Sincronizzati {synced} eventi locali su Google Calendar." if synced > 0 else None


class ContextPrefetchChecker(BaseChecker):
    def __init__(self, tool_manager, memory_manager):
        super().__init__("Context Prefetch")
        self.tool_manager = tool_manager
        self.memory_manager = memory_manager
        self._last_run = 0.0

    async def check(self):
        now = time.time()
        if now - self._last_run < 1200:
            return None
        self._last_run = now
        for name, action in (
            ("weather", {"tool": "weather", "location": os.getenv("DEFAULT_WEATHER_LOCATION", "Roma")}),
            ("news", {"tool": "news", "limit": 3}),
        ):
            tool = self.tool_manager.tools.get(name)
            if not tool:
                continue
            try:
                result = await tool.execute(action) if asyncio.iscoroutinefunction(tool.execute) else await asyncio.to_thread(tool.execute, action)
                if result.get("status") == "ok":
                    await self.memory_manager.add_turn("system", f"[PREFETCH] {name}: {result.get('message', '')}", persist_db=False)
            except Exception as exc:
                print(f"[PREFETCH] {name}: {exc}")
        return None


class ProactiveManager:
    def __init__(self, tool_manager, websocket_manager=None, interval=60, memory_manager=None, voice_manager=None, initial_delay=60):
        self.tool_manager = tool_manager
        self.websocket_manager = websocket_manager
        self.memory_manager = memory_manager
        self.voice_manager = voice_manager
        self.interval = interval
        self.initial_delay = initial_delay
        self.checkers: list[BaseChecker] = [SysMonitorChecker()]
        calendar = tool_manager.tools.get("calendar")
        if calendar:
            self.checkers.extend([CalendarChecker(calendar), CalendarSyncChecker(calendar)])
        if memory_manager:
            self.checkers.append(ContextPrefetchChecker(tool_manager, memory_manager))

    async def _broadcast_alert(self, alert: str):
        if self.websocket_manager:
            await self.websocket_manager.broadcast({"type": "log", "text": f"[AVVISO] {alert}", "level": "warning"})

    async def _speak_alert(self, checker: BaseChecker, alert: str):
        if self.memory_manager:
            await self.memory_manager.add_turn("jarvis", alert, persist_db=False)
        if self.voice_manager and not isinstance(checker, SysMonitorChecker):
            await asyncio.to_thread(self.voice_manager.speak, alert)

    async def start_loop(self):
        if self.initial_delay:
            await asyncio.sleep(self.initial_delay)
        while True:
            for checker in self.checkers:
                try:
                    alert = await checker.check()
                    if alert:
                        await self._broadcast_alert(alert)
                        await self._speak_alert(checker, alert)
                except Exception as exc:
                    print(f"[PROACTIVE] {checker.name}: {exc}")
            await asyncio.sleep(self.interval)
