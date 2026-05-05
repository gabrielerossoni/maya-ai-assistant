import asyncio
import psutil
from datetime import datetime, timedelta
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

class ProactiveManager:
    def __init__(self, tool_manager, interval=60):
        self.tool_manager = tool_manager
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

    async def start_loop(self):
        print("[PROACTIVE] Loop avviato.")
        while True:
            try:
                for checker in self.checkers:
                    alert = await checker.check()
                    if alert:
                        print(f"[PROACTIVE] Trigger attivato ({checker.name}): {alert}")
                        await manager.broadcast({
                            "type": "log",
                            "text": f"🔔 {alert}",
                            "level": "warning"
                        })
                await asyncio.sleep(self.interval)
            except Exception as e:
                print(f"[PROACTIVE] Errore nel loop: {e}")
                await asyncio.sleep(self.interval)
