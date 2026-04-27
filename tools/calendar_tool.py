"""
tools/calendar_tool.py
Gestione calendario locale su file JSON.
Supporta: aggiunta, lista, eliminazione eventi.
"""

import json
import os
from datetime import datetime, timedelta

CALENDAR_FILE = "data/calendar.json"


class CalendarTool:
    """Tool calendario locale basato su file JSON."""

    def initialize(self):
        os.makedirs("data", exist_ok=True)
        if not os.path.exists(CALENDAR_FILE):
            self._save([])
        print(f"[CALENDAR] File: {CALENDAR_FILE}")

    def execute(self, action: dict) -> dict:
        """
        Gestisce operazioni sul calendario.
        action: {"tool": "calendar", "action": "add", "title": "...", "time": "2026-04-26 15:00"}
        """
        op = action.get("action", "list").lower()

        if op == "add":
            return self._add_event(action)
        elif op == "list":
            return self._list_events(action)
        elif op == "delete":
            return self._delete_event(action)
        elif op == "next":
            return self._next_event()
        else:
            return {"status": "error", "message": f"Operazione '{op}' non supportata"}

    # ── Operazioni ────────────────────────────

    def _add_event(self, action: dict) -> dict:
        title    = action.get("title", "Evento senza titolo")
        time_str = action.get("time", "")
        notes    = action.get("notes", "")

        # Parse della data/ora
        dt = self._parse_time(time_str)
        if dt is None:
            return {"status": "error", "message": f"Formato data non valido: '{time_str}'"}

        events = self._load()
        event = {
            "id":      len(events) + 1,
            "title":   title,
            "time":    dt.strftime("%Y-%m-%d %H:%M"),
            "notes":   notes,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        events.append(event)
        events.sort(key=lambda e: e["time"])
        self._save(events)

        print(f"[CALENDAR] Evento aggiunto: '{title}' il {dt.strftime('%d/%m/%Y alle %H:%M')}")
        return {
            "status": "ok",
            "message": f"Evento '{title}' aggiunto per il {dt.strftime('%d/%m/%Y alle %H:%M')}",
            "event": event
        }

    def _list_events(self, action: dict) -> dict:
        events = self._load()
        now    = datetime.now()

        # Filtra: mostra solo eventi futuri
        future = [e for e in events if self._parse_time(e["time"]) >= now]

        if not future:
            return {"status": "ok", "message": "Nessun evento in programma.", "events": []}

        lines = []
        for e in future[:10]:   # max 10 eventi
            dt = self._parse_time(e["time"])
            diff = dt - now
            days = diff.days
            if days == 0:
                when = "oggi"
            elif days == 1:
                when = "domani"
            else:
                when = f"tra {days} giorni"
            lines.append(f"• {e['title']} — {dt.strftime('%d/%m alle %H:%M')} ({when})")

        return {
            "status": "ok",
            "message": "Prossimi eventi:\n" + "\n".join(lines),
            "events": future
        }

    def _delete_event(self, action: dict) -> dict:
        event_id = action.get("id")
        title    = action.get("title", "").lower()

        events = self._load()
        before = len(events)

        if event_id:
            events = [e for e in events if e["id"] != event_id]
        elif title:
            events = [e for e in events if title not in e["title"].lower()]

        self._save(events)
        removed = before - len(events)
        return {"status": "ok", "message": f"{removed} evento/i rimosso/i"}

    def _next_event(self) -> dict:
        events = self._load()
        now    = datetime.now()
        future = [e for e in events if self._parse_time(e["time"]) >= now]

        if not future:
            return {"status": "ok", "message": "Nessun evento imminente."}

        e  = future[0]
        dt = self._parse_time(e["time"])
        return {
            "status": "ok",
            "message": f"Prossimo evento: '{e['title']}' il {dt.strftime('%d/%m alle %H:%M')}",
            "event": e
        }

    # ── Helpers ───────────────────────────────

    def _parse_time(self, time_str: str) -> datetime | None:
        """Accetta vari formati di data/ora."""
        formats = [
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M",
            "%d/%m/%Y %H:%M",
            "%d/%m %H:%M",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue
        return None

    def _load(self) -> list:
        with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, events: list):
        with open(CALENDAR_FILE, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)
