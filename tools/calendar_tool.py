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
GOOGLE_TOKEN_FILE = "data/token.json"
GOOGLE_CREDENTIALS_FILE = "data/credentials.json"
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Imposta qui l'ID del calendario da usare.
# 'primary' = calendario principale dell'account.
# Per trovare altri ID esegui: python -c "from tools.calendar_tool import CalendarTool; c=CalendarTool(); c.initialize(); c.list_google_calendars()"
def _get_calendar_id():
    return os.environ.get("GOOGLE_CALENDAR_ID", "primary")

class CalendarTool:
    """Tool calendario unificato (Locale + Google)."""

    def __init__(self):
        self.google_service = None

    def initialize(self):
        os.makedirs("data", exist_ok=True)
        if not os.path.exists(CALENDAR_FILE):
            self._save([])
        self._init_google_service()

    def _init_google_service(self):
        """Inizializza il servizio Google Calendar se le credenziali sono presenti."""
        if not os.path.exists(GOOGLE_CREDENTIALS_FILE):
            print("[CALENDAR] credentials.json assente. Google Calendar disabilitato.")
            return

        from google.oauth2.credentials import Credentials

        creds = None
        if os.path.exists(GOOGLE_TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_FILE, SCOPES)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                try:
                    flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS_FILE, SCOPES)
                    # Try local server first, fallback to console if it fails (headless)
                    try:
                        creds = flow.run_local_server(port=0)
                    except Exception:
                        print("[CALENDAR] Ambiente headless rilevato o browser non disponibile. Fallback console OAuth.")
                        # flow.run_console() is deprecated in some versions, 
                        # using urn:ietf:wg:oauth:2.0:oob logic if supported by the flow
                        creds = flow.run_console()
                except Exception as e:
                    print(f"[CALENDAR] Errore autenticazione Google: {e}")
                    return
            
            with open(GOOGLE_TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())

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

        # 1. Salvataggio locale preventivo (Sicurezza)
        events = self._load()
        temp_id = len(events) + 1
        event = {
            "id":      temp_id,
            "title":   title,
            "time":    dt.strftime("%Y-%m-%d %H:%M"),
            "notes":   notes,
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        events.append(event)
        self._save(events)
        
        google_success = False
        google_msg = ""

        # 2. Tentativo Google
        if self.google_service:
            try:
                event_body = {
                    'summary': title,
                    'description': notes,
                    'start': {'dateTime': dt.isoformat(), 'timeZone': 'Europe/Rome'},
                    'end': {'dateTime': (dt + timedelta(hours=1)).isoformat(), 'timeZone': 'Europe/Rome'},
                }
                self.google_service.events().insert(calendarId=_get_calendar_id(), body=event_body).execute()
                google_success = True
                google_msg = " (Sincronizzato con Google)"
            except Exception as e:
                google_msg = f" (Errore Google, salvato solo in locale: {e})"

        # 3. Se Google ha avuto successo, rimuovi dal locale
        if google_success:
            events = self._load()
            # Rimuove l'evento appena aggiunto filtrando per titolo e tempo
            events = [e for e in events if not (e["title"] == title and e["time"] == event["time"])]
            self._save(events)
            event["id"] = "google"

        print(f"[CALENDAR] {google_msg if google_success else '[LOCALE]'} Evento: '{title}' il {dt.strftime('%d/%m/%Y alle %H:%M')}")
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
                cal_id = _get_calendar_id()
                events_result = self.google_service.events().list(
                    calendarId=cal_id, timeMin=now_iso,
                    maxResults=50, singleEvents=True,
                    orderBy='startTime'
                ).execute()
                g_events = events_result.get('items', [])
                for ge in g_events:
                    start = ge['start'].get('dateTime', ge['start'].get('date'))
                    dt_g = datetime.fromisoformat(start.replace('Z', '+00:00'))
                    all_events.append({
                        "title": ge.get('summary', 'Senza titolo'),
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

    def sync_local_to_google(self) -> int:
        """Prova a sincronizzare gli eventi locali su Google Calendar. Ritorna il numero di eventi sincronizzati."""
        if not self.google_service:
            return 0

        local_events = self._load()
        if not local_events:
            return 0

        synced_count = 0
        remaining_events = []

        for e in local_events:
            try:
                dt = self._parse_time(e["time"])
                if dt is None: continue

                event_body = {
                    'summary': e["title"],
                    'description': e.get("notes", ""),
                    'start': {'dateTime': dt.isoformat(), 'timeZone': 'Europe/Rome'},
                    'end': {'dateTime': (dt + timedelta(hours=1)).isoformat(), 'timeZone': 'Europe/Rome'},
                }
                self.google_service.events().insert(calendarId=_get_calendar_id(), body=event_body).execute()
                synced_count += 1
                print(f"[CALENDAR] Sincronizzato evento locale: '{e['title']}'")
            except Exception as ex:
                print(f"[CALENDAR] Errore sync evento '{e['title']}': {ex}")
                remaining_events.append(e)

        if synced_count > 0:
            self._save(remaining_events)
        
        return synced_count

    def list_google_calendars(self):
        """Stampa tutti i calendari disponibili con i loro ID."""
        if not self.google_service:
            print("[CALENDAR] Google Calendar non disponibile.")
            return
        result = self.google_service.calendarList().list().execute()
        for cal in result.get('items', []):
            print(f"  {cal['summary']:40s}  ID: {cal['id']}")

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
