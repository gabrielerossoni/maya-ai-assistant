"""Append-only audit log kept next to structured personal data."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLogger:
    def __init__(self, database_path: str | Path = "data/structured_memory.sqlite3"):
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, event TEXT NOT NULL,
                    actor TEXT NOT NULL, details TEXT NOT NULL
                )"""
            )
            connection.commit()

    def record(self, event: str, actor: str = "system", details: dict[str, Any] | None = None) -> None:
        self.initialize()
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO audit_log (created_at, event, actor, details) VALUES (?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), event, actor, json.dumps(details or {}, ensure_ascii=False)),
            )
            connection.commit()

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, created_at, event, actor, details FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        events = []
        for event_id, created_at, event, actor, details in rows:
            try:
                payload = json.loads(details)
            except json.JSONDecodeError:
                payload = {"raw": details}
            events.append({"id": event_id, "created_at": created_at, "event": event, "actor": actor, "details": payload})
        return events

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection
