"""SQLite-backed storage for notes, reminders, facts, and preferences."""

from __future__ import annotations

import json
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
                CREATE TABLE IF NOT EXISTS scheduled_jobs (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    run_at TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    delivered_at TEXT,
                    UNIQUE(kind, run_at)
                );
                CREATE INDEX IF NOT EXISTS scheduled_jobs_due_idx ON scheduled_jobs(run_at);
                """
            )
            self._add_column_if_missing(connection, "reminders", "delivered_at", "TEXT")
            self._add_column_if_missing(connection, "reminders", "delivery_claimed_at", "TEXT")
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

    def claim_due_reminders(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Claim due reminders; caller must mark or release each claim after delivery."""
        due_at = self._as_utc_iso(now or datetime.now(timezone.utc))
        delivered_at = self._now()
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """SELECT id, content, due_at FROM reminders
                   WHERE completed_at IS NULL AND delivered_at IS NULL AND delivery_claimed_at IS NULL AND due_at <= ? ORDER BY due_at ASC""",
                (due_at,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                connection.executemany(
                    "UPDATE reminders SET delivery_claimed_at = ? WHERE id = ? AND delivery_claimed_at IS NULL",
                    [(delivered_at, reminder_id) for reminder_id in ids],
                )
                connection.commit()
        return [dict(row) for row in rows]

    def mark_reminder_delivered(self, reminder_id: int) -> bool:
        delivered_at = self._now()
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """UPDATE reminders SET delivered_at = ?, completed_at = ?, delivery_claimed_at = NULL
                   WHERE id = ? AND delivered_at IS NULL""",
                (delivered_at, delivered_at, reminder_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    def release_reminder_claim(self, reminder_id: int) -> None:
        with closing(self._connect()) as connection:
            connection.execute("UPDATE reminders SET delivery_claimed_at = NULL WHERE id = ? AND delivered_at IS NULL", (reminder_id,))
            connection.commit()

    def schedule_daily_briefing(self, time_of_day: str) -> dict[str, str]:
        if not __import__("re").fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time_of_day):
            raise ValueError("L'orario briefing deve essere HH:MM.")
        return self.set_preference("briefing_time", time_of_day)

    def claim_due_briefings(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = (now or datetime.now().astimezone()).replace(second=0, microsecond=0)
        briefing = self.get_preference("briefing_time")
        if not briefing:
            return []
        hour, minute = map(int, briefing.split(":"))
        scheduled = now.replace(hour=hour, minute=minute)
        if now < scheduled:
            return []
        run_at = self._as_utc_iso(scheduled)
        with closing(self._connect()) as connection:
            try:
                cursor = connection.execute(
                    "INSERT INTO scheduled_jobs (kind, run_at) VALUES ('morning_briefing', ?)", (run_at,)
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT id, kind, run_at FROM scheduled_jobs WHERE kind = 'morning_briefing' AND run_at = ? AND delivered_at IS NULL",
                    (run_at,),
                ).fetchone()
                return [dict(row)] if row else []
            connection.commit()
        return [{"id": cursor.lastrowid, "kind": "morning_briefing", "run_at": run_at}]

    def mark_job_delivered(self, job_id: int) -> bool:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "UPDATE scheduled_jobs SET delivered_at = ? WHERE id = ? AND delivered_at IS NULL", (self._now(), job_id)
            )
            connection.commit()
        return cursor.rowcount == 1

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

    def get_preference(self, key: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT value FROM preferences WHERE key = ?", (key.casefold(),)).fetchone()
        return str(row["value"]) if row else None

    def migrate_legacy_notes(self, legacy_path: str | Path = "data/notes.json") -> int:
        """Copy legacy notes once; source JSON is never changed or removed."""
        path = Path(legacy_path)
        if not path.exists():
            return 0
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return 0
        items = [str(item).strip() for values in payload.values() if isinstance(values, list) for item in values]
        existing = {row["content"] for row in self.list_notes(limit=10_000)}
        created = 0
        for item in items:
            if item and item not in existing:
                self.add_note(item)
                existing.add(item)
                created += 1
        return created

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.row_factory = sqlite3.Row
        return connection

    def _fetch_all(self, query: str, parameters: tuple[Any, ...]) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _add_column_if_missing(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
