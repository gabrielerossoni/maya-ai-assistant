"""
tools/calendar_tool.py
Gestione calendario locale su file JSON.
Supporta: aggiunta, lista, eliminazione eventi.
"""

import json
import os
import datetime
import pickle
from datetime import datetime, timedelta
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

CALENDAR_FILE = "data/calendar.json"
GOOGLE_TOKEN_FILE = "data/token.pickle"
GOOGLE_CREDENTIALS_FILE = "credentials.json"
SCOPES = ['https://www.googleapis.com/auth/calendar']

class CalendarTool:
    """Tool calendario unificato (Locale + Google)."""

    def __init__(self):
        self.google_service = None

    def initialize(self):
        os.makedirs("data", exist_ok=True)
        if not os.path.exists(CALENDAR_FILE):
            self._save([])
        print(f"[CALENDAR] File locale: {CALENDAR_FILE}")
        self._init_google_service()

    def _init_google_service(self):
        """Inizializza il servizio Google Calendar se le credenziali sono presenti."""
        if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
            print("[CALENDAR] credentials.json assente. Google Calendar disabilitato.")
            return

        creds = None
        if os.path.exists(GOOGLE_TOKEN_FILE):
            with open(GOOGLE_TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
                    creds = flow.run_local_server(port=0)
                except Exception as e:
                    print(f"[CALENDAR] Errore autenticazione Google: {e}")
                    return
            
            with open(GOOGLE_TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)

        try:
            self.google_service = build('calendar', 'v3', credentials=creds)
            print("[CALENDAR] Google Calendar sincronizzato.")
        except Exception as e:
            print(f"[CALENDAR] Errore build service Google: {e}")

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

        # 1. Aggiungi a Google se disponibile
        google_msg = ""
        if self.google_service:
            try:
                event_body = {
                    'summary': title,
                    'description': notes,
                    'start': {'dateTime': dt.isoformat(), 'timeZone': 'Europe/Rome'},
                    'end': {'dateTime': (dt + timedelta(hours=1)).isoformat(), 'timeZone': 'Europe/Rome'},
                }
                self.google_service.events().insert(calendarId='primary', body=event_body).execute()
                google_msg = " (Sincronizzato con Google)"
            except Exception as e:
                google_msg = f" (Errore Google: {e})"

        # 2. Aggiungi locale
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

        print(f"[CALENDAR] Evento aggiunto: '{title}' il {dt.strftime('%d/%m/%Y alle %H:%M')}{google_msg}")
        return {
            "status": "ok",
            "message": f"Evento '{title}' aggiunto per il {dt.strftime('%d/%m/%Y alle %H:%M')}{google_msg}",
            "event": event
        }

    def _list_events(self, action: dict) -> dict:
        now = datetime.now()
        now_iso = now.astimezone().isoformat()
        
        all_events = []
        
        # 1. Recupera da Google
        if self.google_service:
            try:
                events_result = self.google_service.events().list(
                    calendarId='primary', timeMin=now_iso,
                    maxResults=10, singleEvents=True,
                    orderBy='startTime'
                ).execute()
                g_events = events_result.get('items', [])
                for ge in g_events:
                    start = ge['start'].get('dateTime', ge['start'].get('date'))
                    # Normalizza formato per il parser locale
                    dt_g = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    all_events.append({
                        "title": f"[G] {ge.get('summary', 'Senza titolo')}",
                        "time": dt_g.strftime("%Y-%m-%d %H:%M"),
                        "source": "google"
                    })
            except Exception as e:
                print(f"[CALENDAR] Errore fetch Google: {e}")

        # 2. Recupera locale
        local_events = self._load()
        for le in local_events:
            if self._parse_time(le["time"]) >= now:
                all_events.append({**le, "source": "local"})

        # Ordina per tempo
        all_events.sort(key=lambda e: e["time"])
        
        if not all_events:
            return {"status": "ok", "message": "Nessun evento in programma.", "events": []}

        lines = []
        for e in all_events[:10]:
            dt = self._parse_time(e["time"])
            diff = dt - now
            days = diff.days
            if days == 0: when = "oggi"
            elif days == 1: when = "domani"
            else: when = f"tra {days} giorni"
            lines.append(f"• {e['title']} — {dt.strftime('%d/%m alle %H:%M')} ({when})")

        return {
            "status": "ok",
            "message": "Prossimi eventi:\n" + "\n".join(lines),
            "events": all_events
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
