"""SQLite-backed storage for notes, reminders, facts, and preferences."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class StructuredMemory:
    """Small synchronous repository for deterministic personal-data operations."""

    def __init__(self, database_path: str | Path = "data/structured_memory.sqlite3"):
        self.database_path = Path(database_path)

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY,
                    content TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS reminders_due_at_idx ON reminders(due_at);
                CREATE TABLE IF NOT EXISTS facts (
                    id INTEGER PRIMARY KEY,
                    subject TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(subject)
                );
                CREATE TABLE IF NOT EXISTS preferences (
                    id INTEGER PRIMARY KEY,
                    key TEXT NOT NULL UNIQUE,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            connection.commit()

    def add_note(self, content: str) -> dict[str, Any]:
        content = self._required_text(content, "Il contenuto della nota")
        now = self._now()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "INSERT INTO notes (content, created_at, updated_at) VALUES (?, ?, ?)",
                (content, now, now),
            )
            connection.commit()
        return {"id": cursor.lastrowid, "content": content, "created_at": now}

    def list_notes(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._fetch_all(
            "SELECT id, content, created_at, updated_at FROM notes ORDER BY id DESC LIMIT ?", (limit,)
        )

    def add_reminder(self, content: str, due_at: datetime) -> dict[str, Any]:
        content = self._required_text(content, "Il contenuto del promemoria")
        due_at = self._as_utc_iso(due_at)
        with closing(self._connect()) as connection:
            cursor = connection.execute("INSERT INTO reminders (content, due_at) VALUES (?, ?)", (content, due_at))
            connection.commit()
        return {"id": cursor.lastrowid, "content": content, "due_at": due_at}

    def due_reminders(self, now: datetime | None = None) -> list[dict[str, Any]]:
        due_at = self._as_utc_iso(now or datetime.now(timezone.utc))
        return self._fetch_all(
            """SELECT id, content, due_at FROM reminders
               WHERE completed_at IS NULL AND due_at <= ? ORDER BY due_at ASC""",
            (due_at,),
        )

    def remember_fact(self, subject: str, value: str) -> dict[str, str]:
        subject = self._required_text(subject, "Il soggetto")
        value = self._required_text(value, "Il valore")
        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO facts (subject, value, created_at, updated_at) VALUES (?, ?, ?, ?)
                   ON CONFLICT(subject) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                (subject.casefold(), value, now, now),
            )
            connection.commit()
        return {"subject": subject, "value": value, "updated_at": now}

    def find_facts(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        query = self._required_text(query, "La ricerca")
        pattern = f"%{query.casefold()}%"
        return self._fetch_all(
            """SELECT subject, value, updated_at FROM facts
               WHERE subject LIKE ? OR value LIKE ? ORDER BY updated_at DESC LIMIT ?""",
            (pattern, pattern, limit),
        )

    def set_preference(self, key: str, value: str) -> dict[str, str]:
        key = self._required_text(key, "La chiave")
        value = self._required_text(value, "Il valore")
        now = self._now()
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                (key.casefold(), value, now),
            )
            connection.commit()
        return {"key": key, "value": value, "updated_at": now}

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _fetch_all(self, query: str, parameters: tuple[Any, ...]) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _required_text(value: str, label: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError(f"{label} non puo essere vuoto.")
        return text

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _as_utc_iso(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
