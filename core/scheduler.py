"""Single persistent scheduler for reminders and daily briefings."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Awaitable, Callable

from .audit.logger import AuditLogger
from .memory.structured import StructuredMemory

Deliver = Callable[[str], Awaitable[None]]


class PersistentScheduler:
    def __init__(
        self, memory: StructuredMemory, deliver: Deliver, audit: AuditLogger | None = None, interval: float = 30
    ):
        self.memory, self.deliver, self.audit, self.interval = (
            memory,
            deliver,
            audit or AuditLogger(memory.database_path),
            interval,
        )

    async def tick(self, briefing_factory: Callable[[], Awaitable[str | None]] | None = None) -> None:
        for reminder in self.memory.claim_due_reminders():
            message = f"Promemoria: {reminder['content']}"
            try:
                await self.deliver(message)
                self.memory.mark_reminder_delivered(reminder["id"])
                self.audit.record("reminder_delivered", details={"reminder_id": reminder["id"]})
            except Exception as exc:
                self.memory.release_reminder_claim(reminder["id"])
                self.audit.record(
                    "reminder_delivery_error", details={"reminder_id": reminder["id"], "type": type(exc).__name__}
                )
        if briefing_factory:
            for job in self.memory.claim_due_briefings(datetime.now().astimezone()):
                try:
                    briefing = await briefing_factory()
                    if briefing:
                        await self.deliver(briefing)
                        self.memory.mark_job_delivered(job["id"])
                        self.audit.record("briefing_delivered")
                except Exception as exc:
                    self.audit.record("briefing_delivery_error", details={"type": type(exc).__name__})

    async def start(self, briefing_factory: Callable[[], Awaitable[str | None]] | None = None) -> None:
        while True:
            try:
                await self.tick(briefing_factory)
            except Exception as exc:
                self.audit.record("scheduler_error", details={"type": type(exc).__name__})
            await asyncio.sleep(self.interval)
