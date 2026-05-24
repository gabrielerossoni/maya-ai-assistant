import asyncio
import json
import os
import time
from datetime import datetime, timedelta

import httpx
import psutil

from .websocket_manager import manager


class BaseChecker:
    def __init__(self, name):
        self.name = name

    async def check(self):
        """Ritorna una stringa di avviso se il trigger è attivo, altrimenti None."""
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
            return f"⚠️ Allerta Sistema: Utilizzo CPU al {cpu}%!"
        if ram > self.ram_threshold:
            return f"⚠️ Allerta Sistema: Utilizzo RAM al {ram}%!"
        return None

class CalendarChecker(BaseChecker):
    def __init__(self, calendar_tool):
        super().__init__("Calendar")
        self.calendar_tool = calendar_tool
        self.last_notified_event = None

    async def check(self):
        # Utilizza il tool esistente per avere i dati
        res = self.calendar_tool.execute({"action": "next"})
        if res.get("status") == "ok" and "event" in res:
            event = res["event"]
            event_time = datetime.strptime(event["time"], "%Y-%m-%d %H:%M")
            diff = event_time - datetime.now()

            # Notifica se l'evento è tra meno di 15 minuti e non è ancora stato notificato
            if timedelta(0) < diff < timedelta(minutes=15):
                if self.last_notified_event != event["id"]:
                    self.last_notified_event = event["id"]
                    return f"📅 Promemoria: L'evento '{event['title']}' inizia tra poco ({event['time']})."
        return None

class CalendarSyncChecker(BaseChecker):
    def __init__(self, calendar_tool):
        super().__init__("Calendar Sync")
        self.calendar_tool = calendar_tool

    async def check(self):
        # Tenta la sincronizzazione in background
        synced = self.calendar_tool.sync_local_to_google()
        if synced > 0:
            return f"Sincronizzati {synced} eventi locali su Google Calendar."
        return None

class ContextualSensorChecker(BaseChecker):
    """
    Livello 1: soglie hard (veloce, no LLM).
    Livello 2: se anomalia rilevata, chiede all'LLM se intervenire.
    LLM chiamato SOLO quando le soglie fisse sono superate.
    """

    HARD_THRESHOLDS = {
        "temp_high":     lambda s: s.get("temp", 0) > 28,
        "temp_low":      lambda s: s.get("temp", 99) < 14,
        "humidity_high": lambda s: s.get("humidity", 0) > 75,
    }

    _PROACTIVE_PROMPT = """Sei il modulo di Ragionamento Proattivo di MAYA.
Analizza i dati sensori e la memoria recente. Decidi se serve un intervento.

REGOLE:
- Intervieni SOLO se il disagio è chiaro e non già gestito.
- Se la memoria recente mostra che l'utente ha già detto di voler gestire da solo, NON intervenire.
- Sii conciso: una frase sola all'utente.

Rispondi SOLO con JSON:
{
  "trigger": "motivo breve o 'none'",
  "suggestion": "frase da dire all'utente (vuota se trigger=none)"
}"""

    COOLDOWN = 600  # secondi — non ripetere lo stesso trigger per 10 minuti

    def __init__(self, tool_manager, memory_manager):
        super().__init__("ContextualSensor")
        self.tool_manager = tool_manager
        self.memory_manager = memory_manager
        self._last_notified: dict = {}

    async def check(self) -> str | None:
        arduino = self.tool_manager.tools.get("arduino")
        if not arduino:
            return None

        sensor = await asyncio.to_thread(arduino.get_sensor_data)
        if not sensor:
            return None

        hw_state = arduino.sim_state.copy()
        hw_state.update(sensor)

        # Livello 1: soglie hard
        now = time.time()
        triggered = [
            k for k, fn in self.HARD_THRESHOLDS.items()
            if fn(hw_state) and now - self._last_notified.get(k, 0) > self.COOLDOWN
        ]
        if not triggered:
            return None

        # Livello 2: chiedi all'LLM
        recent_context = await self.memory_manager.get_context(
            query="temperatura umidità comfort casa", top_k=3
        )
        user_msg = (
            f"Stato sensori: temp={hw_state.get('temp')}°C, "
            f"umidità={hw_state.get('humidity')}%, "
            f"luce={'ON' if hw_state.get('light') else 'OFF'}.\n"
            f"Anomalie rilevate: {', '.join(triggered)}.\n"
            f"Memoria recente: {str(recent_context)[-500:]}"
        )

        result = await self._ask_llm(user_msg)
        if not result or result.get("trigger", "none") == "none":
            return None

        # Aggiorna cooldown per i trigger processati
        for t in triggered:
            self._last_notified[t] = now

        return result.get("suggestion", "")

    async def _ask_llm(self, user_msg: str) -> dict:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return {"trigger": "none"}
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": os.getenv("GROQ_ROUTER_MODEL", "llama-3.1-8b-instant"),
                        "messages": [
                            {"role": "system", "content": self._PROACTIVE_PROMPT},
                            {"role": "user", "content": user_msg},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.1,
                        "max_tokens": 150,
                    },
                )
                return json.loads(resp.json()["choices"][0]["message"]["content"])
        except Exception as e:
            print(f"[CONTEXTUAL_SENSOR] Errore LLM: {e}")
            return {"trigger": "none"}


class ContextPrefetchChecker(BaseChecker):
    """Pre-carica dati freschi nel context ogni 20 min (silent, nessun broadcast)."""

    def __init__(self, tool_manager, memory_manager):
        super().__init__("ContextPrefetch")
        self.tool_manager = tool_manager
        self.memory_manager = memory_manager
        self._last_run = 0

    async def check(self):
        now = time.time()
        if now - self._last_run < 1200:  # 20 minuti
            return None
        self._last_run = now

        # Prefetch meteo
        weather_tool = self.tool_manager.tools.get("weather")
        if weather_tool:
            try:
                location = os.getenv("DEFAULT_WEATHER_LOCATION", "Roma")
                action = {"tool": "weather", "location": location}
                if asyncio.iscoroutinefunction(weather_tool.execute):
                    result = await weather_tool.execute(action)
                else:
                    result = weather_tool.execute(action)
                if result.get("status") == "ok":
                    await self.memory_manager.add_turn(
                        "system", f"[PREFETCH] Meteo attuale: {result.get('message', '')}"
                    )
            except Exception as e:
                print(f"[PREFETCH] Errore weather: {e}")

        # Prefetch notizie (solo titoli)
        news_tool = self.tool_manager.tools.get("news")
        if news_tool:
            try:
                action = {"tool": "news", "limit": 3}
                if asyncio.iscoroutinefunction(news_tool.execute):
                    result = await news_tool.execute(action)
                else:
                    result = news_tool.execute(action)
                if result.get("status") == "ok":
                    news_list = result.get("news", [])
                    if news_list:
                        titles = "; ".join(n.get("title", "") for n in news_list[:3])
                    else:
                        titles = result.get("message", "")
                    if titles:
                        await self.memory_manager.add_turn(
                            "system", f"[PREFETCH] Ultime notizie: {titles}"
                        )
            except Exception as e:
                print(f"[PREFETCH] Errore news: {e}")

        return None  # silent — nessun broadcast


class ProactiveManager:
    def __init__(self, tool_manager, websocket_manager=None, interval=60, memory_manager=None):
        self.tool_manager = tool_manager
        self.websocket_manager = websocket_manager
        self.memory_manager = memory_manager
        self.interval = interval
        self.checkers = []
        self._initialize_checkers()

    def _initialize_checkers(self):
        # Inizializza i checker base
        self.checkers.append(SysMonitorChecker())

        # Se il tool calendario è registrato, aggiungi il checker
        calendar_tool = self.tool_manager.tools.get("calendar")
        if calendar_tool:
            self.checkers.append(CalendarChecker(calendar_tool))
            self.checkers.append(CalendarSyncChecker(calendar_tool))

        # Prefetch silenzioso meteo+news ogni 20 min
        if self.memory_manager:
            self.checkers.append(ContextPrefetchChecker(self.tool_manager, self.memory_manager))
            self.checkers.append(ContextualSensorChecker(self.tool_manager, self.memory_manager))

    async def start_loop(self):
        while True:
            try:
                for checker in self.checkers:
                    alert = await checker.check()
                    if alert:
                        print(f"[PROACTIVE] Trigger attivato ({checker.name}): {alert}")
                        if self.websocket_manager:
                            if isinstance(checker, ContextualSensorChecker):
                                await self.websocket_manager.broadcast({
                                    "type": "proactive_suggestion",
                                    "text": alert,
                                    "level": "suggestion",
                                })
                            else:
                                await self.websocket_manager.broadcast({
                                    "type": "log",
                                    "text": f"🔔 {alert}",
                                    "level": "warning",
                                })
                await asyncio.sleep(self.interval)
            except Exception as e:
                print(f"[PROACTIVE] Errore nel loop: {e}")
                await asyncio.sleep(self.interval)
