"""
automation_engine.py - Automation Engine intelligente per Maya.

Sostituisce il dizionario AUTOMATIONS statico con un sistema OO completo:
- Scene con priorità, condizioni e azioni tipizzate
- Trigger automatici (tempo, contesto, eventi)
- Conflict detection e recovery
- Logging strutturato degli eventi
- Automazioni temporanee con scadenza
- Event bus interno
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Callable, Coroutine

from .context_manager import context, ContextManager
from .device_registry import registry, DeviceRegistry

logger = logging.getLogger("maya.automation")


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITÀ
# ─────────────────────────────────────────────────────────────────────────────

class Priority(IntEnum):
    LOW      = 10
    NORMAL   = 50
    HIGH     = 80
    CRITICAL = 100


# ─────────────────────────────────────────────────────────────────────────────
# ACTION — unità atomica di esecuzione
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Action:
    """
    Rappresenta un comando da inviare a un tool.
    
    Struttura pulita e validabile, compatibile con ToolManager.execute().
    """
    tool:    str
    params:  dict = field(default_factory=dict)
    delay:   float = 0.0     # secondi di attesa prima dell'esecuzione
    retry:   int   = 1       # tentativi in caso di errore
    timeout: float = 5.0     # timeout per tool lenti (es. Arduino seriale)

    def to_tool_action(self) -> dict:
        """Converte in formato atteso da ToolManager.execute()."""
        return {"tool": self.tool, **self.params}

    def __repr__(self):
        return f"Action({self.tool}, {self.params})"


# Helper costruttori per leggibilità delle scene
def arduino(target: str, value: Any = None, **kwargs) -> Action:
    params = {"target": target}
    if value is not None:
        params["value"] = value
    params.update(kwargs)
    return Action(tool="arduino", params={"op": "SET", **params})

def spotify(command: str, **kwargs) -> Action:
    return Action(tool="spotify", params={"command": command, **kwargs})

def timer_action(minutes: int, message: str) -> Action:
    return Action(tool="timer", params={"minutes": minutes, "message": message})

def weather_action() -> Action:
    return Action(tool="weather", params={"location": None})

def news_action(limit: int = 3) -> Action:
    return Action(tool="news", params={"limit": limit})

def calendar_action(act: str = "list") -> Action:
    return Action(tool="calendar", params={"action": act})


# ─────────────────────────────────────────────────────────────────────────────
# CONDITION — predicato sul contesto
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Condition:
    """
    Condizione booleana valutata sul ContextManager.
    
    Esempi:
        Condition({"time_slot": "night"})
        Condition({"presence": "home", "weather": ["rain", "cloud"]})
        Condition({"presence": {"not": "away"}})
    """
    requirements: dict = field(default_factory=dict)

    def evaluate(self) -> bool:
        if not self.requirements:
            return True
        return context.matches(self.requirements)

    def __repr__(self):
        return f"Condition({self.requirements})"


# ─────────────────────────────────────────────────────────────────────────────
# TRIGGER — cosa attiva l'automazione
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Trigger:
    """
    Definisce come viene attivata un'automazione.
    
    type: "manual"   → solo su richiesta esplicita
          "time"     → ogni giorno a un orario (HH:MM)
          "event"    → su evento del bus interno
          "context"  → quando il contesto soddisfa le condizioni
    """
    type:       str   = "manual"
    time:       str   = ""       # "HH:MM" per type="time"
    event_name: str   = ""       # nome evento per type="event"
    context:    dict  = field(default_factory=dict)  # condizioni per type="context"


# ─────────────────────────────────────────────────────────────────────────────
# SCENE — raccolta di azioni con metadati
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Scene:
    """
    Insieme di azioni con nome, condizioni e priorità.
    Sostituisce le liste nel dizionario AUTOMATIONS.
    """
    name:       str
    actions:    list[Action]
    priority:   Priority     = Priority.NORMAL
    conditions: list[Condition] = field(default_factory=list)
    exclusive:  bool         = False   # se True, sospende altre scene attive
    cooldown:   float        = 0.0     # secondi minimi tra due esecuzioni
    _last_run:  float        = field(default=0.0, init=False, repr=False)

    def can_run(self) -> bool:
        """Verifica condizioni e cooldown."""
        if time.time() - self._last_run < self.cooldown:
            return False
        return all(c.evaluate() for c in self.conditions)

    def mark_run(self):
        self._last_run = time.time()


# ─────────────────────────────────────────────────────────────────────────────
# AUTOMATION — scene + trigger (unità completa)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Automation:
    """
    Unità completa: una Scene con uno o più Trigger associati.
    Supporta scadenza (per automazioni temporanee).
    """
    scene:      Scene
    triggers:   list[Trigger]     = field(default_factory=list)
    aliases:    list[str]         = field(default_factory=list)
    enabled:    bool              = True
    expires_at: float | None      = None   # timestamp Unix, None = permanente
    tags:       list[str]         = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.scene.name

    def is_valid(self) -> bool:
        """Ritorna False se scaduta."""
        if not self.enabled:
            return False
        if self.expires_at and time.time() > self.expires_at:
            self.enabled = False
            return False
        return True

    def matches_input(self, text: str) -> bool:
        """Controlla se il testo attiva questa automazione (nome o alias)."""
        lower = text.lower().strip()
        if self.name in lower:
            return True
        return any(alias in lower for alias in self.aliases)


# ─────────────────────────────────────────────────────────────────────────────
# EVENT BUS — comunicazione interna disaccoppiata
# ─────────────────────────────────────────────────────────────────────────────

class EventBus:
    """
    Bus di eventi interno. Permette a qualsiasi componente di pubblicare
    eventi e ad altri di reagire senza accoppiamento diretto.
    
    Uso:
        bus.subscribe("presence_changed", my_handler)
        bus.publish("presence_changed", {"presence": "home"})
    """

    def __init__(self):
        self._handlers: dict[str, list[Callable]] = {}

    def subscribe(self, event: str, handler: Callable[[dict], Coroutine]):
        self._handlers.setdefault(event, []).append(handler)

    def unsubscribe(self, event: str, handler: Callable):
        if event in self._handlers:
            self._handlers[event] = [h for h in self._handlers[event] if h != handler]

    async def publish(self, event: str, data: dict = None):
        data = data or {}
        handlers = self._handlers.get(event, []) + self._handlers.get("*", [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event, data)
                else:
                    handler(event, data)
            except Exception as e:
                logger.error(f"[BUS] Errore handler '{event}': {e}")


# ─────────────────────────────────────────────────────────────────────────────
# AUTOMATION ENGINE — orchestratore principale
# ─────────────────────────────────────────────────────────────────────────────

class AutomationEngine:
    """
    Motore centrale che gestisce tutte le automazioni di Maya.
    
    Responsabilità:
    - Registrare automazioni (scene + trigger)
    - Eseguire scene con priorità, conflict detection e retry
    - Gestire trigger temporali e di contesto
    - Loggare ogni evento con struttura
    - Esporre l'event bus per integrazioni esterne
    """

    def __init__(self, tool_manager=None):
        self._tool_manager   = tool_manager
        self._automations:   dict[str, Automation] = {}
        self._active_tasks:  dict[str, asyncio.Task] = {}
        self._scheduler_task: asyncio.Task | None = None
        self.bus = EventBus()
        self._event_log: list[dict] = []   # ultimi N eventi eseguiti

    # ── Registrazione ─────────────────────────────────────────────────────────

    def register(self, automation: Automation):
        """Registra un'automazione nel motore."""
        self._automations[automation.name] = automation
        logger.debug(f"[ENGINE] Registrata automazione: '{automation.name}'")

    def register_all(self, automations: list[Automation]):
        for a in automations:
            self.register(a)

    def add_temporary(self, automation: Automation, duration_seconds: float):
        """Registra un'automazione che scade dopo N secondi."""
        automation.expires_at = time.time() + duration_seconds
        self.register(automation)
        logger.info(f"[ENGINE] Automazione temporanea '{automation.name}' scade in {duration_seconds}s")

    def remove(self, name: str):
        self._automations.pop(name, None)

    # ── Risoluzione input → automazione ──────────────────────────────────────

    def resolve(self, user_input: str) -> Automation | None:
        """
        Trova la prima automazione valida che matcha l'input.
        Ordina per priorità decrescente.
        """
        import re
        lower = re.sub(r"\s+", " ", user_input.lower().strip())

        candidates = [
            a for a in self._automations.values()
            if a.is_valid() and a.matches_input(lower)
        ]
        if not candidates:
            return None

        return max(candidates, key=lambda a: a.scene.priority)

    def resolve_by_name(self, name: str) -> Automation | None:
        return self._automations.get(name)

    def list_automations(self) -> list[str]:
        return [name for name, a in self._automations.items() if a.is_valid()]

    # ── Esecuzione ────────────────────────────────────────────────────────────

    async def execute(self, automation: Automation, source: str = "manual") -> dict:
        """
        Esegue una scena con:
        - verifica can_run() (condizioni + cooldown)
        - conflict detection
        - retry su errore
        - aggiornamento context e registry
        - logging strutturato
        - event bus publish
        """
        scene = automation.scene

        if not scene.can_run():
            reason = "cooldown" if time.time() - scene._last_run < scene.cooldown else "condizioni non soddisfatte"
            logger.info(f"[ENGINE] '{scene.name}' bloccata: {reason}")
            return {"status": "skipped", "reason": reason}

        # Conflict detection: se scene exclusive, cancella altre in esecuzione
        if scene.exclusive and scene.name in self._active_tasks:
            task = self._active_tasks[scene.name]
            if not task.done():
                logger.warning(f"[ENGINE] '{scene.name}' già in esecuzione, skip")
                return {"status": "skipped", "reason": "already_running"}

        logger.info(f"[ENGINE] Esecuzione '{scene.name}' (priorità={scene.priority}, source={source})")

        results = []
        errors  = []
        start_ts = time.time()

        for action in scene.actions:
            if action.delay > 0:
                await asyncio.sleep(action.delay)

            result = await self._execute_action_with_retry(action, scene.name)
            results.append(result)

            if result.get("status") == "error":
                errors.append({"action": str(action), "error": result.get("message")})
                logger.warning(f"[ENGINE] '{scene.name}' — errore in {action}: {result.get('message')}")

            # Aggiorna registry dopo azioni Arduino
            if action.tool == "arduino" and result.get("status") == "ok":
                state = result.get("state", {})
                if state:
                    registry.update_from_arduino_state(state, scene=scene.name)

        # Aggiorna contesto
        scene.mark_run()
        context.set_scene(scene.name)

        elapsed = round(time.time() - start_ts, 3)
        status  = "ok" if not errors else "partial"

        event_entry = {
            "scene":   scene.name,
            "source":  source,
            "status":  status,
            "errors":  errors,
            "elapsed": elapsed,
            "ts":      start_ts,
        }
        self._log_event(event_entry)

        await self.bus.publish("scene_executed", event_entry)

        logger.info(f"[ENGINE] '{scene.name}' completata in {elapsed}s — status={status}")
        return {"status": status, "results": results, "errors": errors, "elapsed": elapsed}

    async def execute_by_name(self, name: str, source: str = "manual") -> dict:
        automation = self._automations.get(name)
        if not automation:
            return {"status": "error", "message": f"Automazione '{name}' non trovata"}
        return await self.execute(automation, source=source)

    async def execute_actions(self, actions: list[Action], source: str = "manual") -> list[dict]:
        """Esegui una lista di azioni raw (compatibilità con il vecchio sistema)."""
        results = []
        for action in actions:
            result = await self._execute_action_with_retry(action, source)
            results.append({"tool": action.tool, "result": result})
        return results

    # ── Esecuzione singola azione con retry ───────────────────────────────────

    async def _execute_action_with_retry(self, action: Action, scene_name: str) -> dict:
        if not self._tool_manager:
            return {"status": "error", "message": "ToolManager non configurato"}

        last_result = {}
        for attempt in range(max(1, action.retry)):
            try:
                tool_action = action.to_tool_action()
                result = await asyncio.wait_for(
                    self._tool_manager.execute(tool_action),
                    timeout=action.timeout,
                )
                if result.get("status") != "error":
                    return result
                last_result = result
                if attempt < action.retry - 1:
                    logger.debug(f"[ENGINE] Retry {attempt+1}/{action.retry} per {action}")
                    await asyncio.sleep(0.5 * (attempt + 1))
            except asyncio.TimeoutError:
                last_result = {"status": "error", "message": f"timeout ({action.timeout}s)"}
                logger.warning(f"[ENGINE] Timeout su {action} (scena: {scene_name})")
            except Exception as e:
                last_result = {"status": "error", "message": str(e)}
                logger.error(f"[ENGINE] Eccezione su {action}: {e}")

        return last_result

    # ── Scheduler temporale ───────────────────────────────────────────────────

    async def start_scheduler(self):
        """Loop asincrono che controlla trigger temporali e di contesto."""
        logger.info("[ENGINE] Scheduler avviato")
        while True:
            try:
                now = datetime.now().strftime("%H:%M")
                snap = context.snapshot()

                for automation in list(self._automations.values()):
                    if not automation.is_valid():
                        continue

                    for trigger in automation.triggers:
                        if trigger.type == "time" and trigger.time == now:
                            # Evita esecuzioni multiple nello stesso minuto
                            last = automation.scene._last_run
                            if time.time() - last > 59:
                                logger.info(f"[SCHEDULER] Trigger temporale: '{automation.name}' ({now})")
                                asyncio.create_task(
                                    self.execute(automation, source=f"scheduler:{now}")
                                )

                        elif trigger.type == "context" and trigger.context:
                            if context.matches(trigger.context):
                                last = automation.scene._last_run
                                if time.time() - last > 300:  # max ogni 5 min per context trigger
                                    logger.info(f"[SCHEDULER] Trigger contesto: '{automation.name}'")
                                    asyncio.create_task(
                                        self.execute(automation, source="context_trigger")
                                    )

            except Exception as e:
                logger.error(f"[SCHEDULER] Errore: {e}")

            await asyncio.sleep(60)  # controlla ogni minuto

    # ── Event log ─────────────────────────────────────────────────────────────

    def _log_event(self, entry: dict):
        self._event_log.append(entry)
        if len(self._event_log) > 200:
            self._event_log = self._event_log[-200:]

    def get_event_log(self, limit: int = 20) -> list[dict]:
        return self._event_log[-limit:]

    def get_last_scene(self) -> str | None:
        return context.get("active_scene")


# ─────────────────────────────────────────────────────────────────────────────
# SCENE PREDEFINITE — conversione da AUTOMATIONS statico
# ─────────────────────────────────────────────────────────────────────────────

def build_default_automations() -> list[Automation]:
    """
    Costruisce tutte le automazioni predefinite usando il nuovo sistema OO.
    Ogni scena ha: azioni tipizzate, priorità, condizioni, cooldown, alias.
    """

    return [

        # ── Buonanotte ────────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="buonanotte",
                priority=Priority.HIGH,
                cooldown=300,
                actions=[
                    arduino("light", 0),
                    arduino("servo", 0),
                    Action(tool="network", params={"message": "GOODNIGHT"}),
                    Action(tool="system", params={"command": "shutdown"}),
                ],
            ),
            aliases=["buona notte", "bonne nuit", "notte", "vado a dormire", "va a dormire"],
            triggers=[
                Trigger(type="time", time="23:30"),
            ],
        ),

        # ── Buongiorno ────────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="buongiorno",
                priority=Priority.HIGH,
                cooldown=3600,
                actions=[
                    arduino("light", 1),
                    arduino("rgb", 0xFFD580),
                    arduino("relay", 1),
                    arduino("servo", 0),
                    spotify("search", query="buongiorno playlist mattina"),
                    weather_action(),
                    news_action(limit=5),
                    calendar_action("list"),
                ],
            ),
            aliases=["buon giorno", "morning"],
            triggers=[
                Trigger(type="time", time="07:00"),
                Trigger(type="context", context={"time_slot": "morning", "presence": "home"}),
            ],
        ),

        # ── Sveglia ───────────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="sveglia",
                priority=Priority.CRITICAL,
                actions=[
                    arduino("buzzer", 1),
                    arduino("light", 1),
                    arduino("rgb", 0xFFFFFF),
                    arduino("relay", 1),
                    spotify("search", query="energetic morning wake up"),
                ],
            ),
            aliases=["svegliami", "dammi la sveglia"],
        ),

        # ── Modalità lavoro ───────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="modalità lavoro",
                priority=Priority.NORMAL,
                cooldown=60,
                actions=[
                    arduino("light", 1),
                    Action(tool="system", params={"command": "open_browser"}),
                    Action(tool="network", params={"message": "WORK_MODE"}),
                ],
            ),
            aliases=["lavoro", "work mode"],
            triggers=[
                Trigger(type="event", event_name="app_opened:vscode"),
                Trigger(type="event", event_name="app_opened:jetbrains"),
            ],
        ),

        # ── Modalità studio ───────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="modalità studio",
                priority=Priority.NORMAL,
                cooldown=60,
                actions=[
                    arduino("light", 1),
                    arduino("relay", 0),
                    arduino("rgb", 0xFFEE99),
                ],
            ),
            aliases=["studio"],
        ),

        # ── Modalità film ─────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="modalità film",
                priority=Priority.NORMAL,
                exclusive=True,
                actions=[
                    arduino("light", 0),
                    arduino("relay", 1),
                    arduino("rgb", 0x220000),
                ],
            ),
            aliases=["film", "cinema", "guardo un film"],
        ),

        # ── Modalità gaming ───────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="modalità gaming",
                priority=Priority.NORMAL,
                cooldown=60,
                actions=[
                    arduino("light", 0),
                    arduino("relay", 1),
                    Action(tool="system", params={"command": "open_browser"}),
                ],
            ),
            aliases=["gaming", "gioco"],
            triggers=[
                Trigger(type="event", event_name="headphones_connected"),
            ],
        ),

        # ── Modalità relax ────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="modalità relax",
                priority=Priority.LOW,
                actions=[
                    arduino("light", 0),
                    arduino("relay", 1),
                    arduino("rgb", 0x440055),
                ],
            ),
            aliases=["relax"],
        ),

        # ── Modalità notte ────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="modalità notte",
                priority=Priority.NORMAL,
                cooldown=300,
                conditions=[Condition({"time_slot": ["evening", "night"]})],
                actions=[
                    arduino("light", 0),
                    arduino("relay", 0),
                    arduino("rgb", 0x000022),
                    arduino("servo", 0),
                    spotify("pause"),
                ],
            ),
            triggers=[
                Trigger(type="time", time="23:00"),
                Trigger(type="context", context={"time_slot": "night", "presence": "home"}),
            ],
        ),

        # ── Modalità ospite ───────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="modalità ospite",
                priority=Priority.HIGH,
                actions=[
                    arduino("light", 1),
                    arduino("relay", 1),
                    arduino("rgb", 0xFFFFFF),
                    arduino("servo", 90),
                ],
            ),
            aliases=["ospite"],
        ),

        # ── Ospiti in arrivo ──────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="ospiti in arrivo",
                priority=Priority.HIGH,
                cooldown=120,
                actions=[
                    arduino("servo2", 90),
                    arduino("servo", 90),
                    arduino("neopixel", 0xFFEECC, effect=1),
                    Action(tool="arduino", params={"op": "SET", "target": "buzzer2", "melody": "startup"}),
                ],
            ),
            aliases=["arrivano ospiti", "stanno arrivando"],
        ),

        # ── Vado fuori ────────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="vado fuori",
                priority=Priority.HIGH,
                cooldown=30,
                actions=[
                    arduino("light", 0),
                    arduino("relay", 0),
                    arduino("rgb", 0),
                    arduino("servo", 0),
                    Action(tool="arduino", params={"op": "SET", "target": "buzzer", "value": 1}),
                    spotify("pause"),
                    weather_action(),
                ],
            ),
            aliases=["esco", "me ne vado", "vado via"],
            triggers=[
                Trigger(type="event", event_name="phone_left_wifi"),
            ],
        ),

        # ── Sono rientrato ────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="sono rientrato",
                priority=Priority.HIGH,
                cooldown=30,
                actions=[
                    arduino("light", 1),
                    arduino("servo", 90),
                    arduino("rgb", 0xFF8C42),
                    arduino("relay", 1),
                    spotify("search", query="relax after work playlist"),
                    timer_action(5, "Ricordati di chiudere la porta!"),
                    news_action(limit=3),
                ],
            ),
            aliases=["sono tornato", "rientro", "torno"],
            triggers=[
                Trigger(type="event", event_name="phone_joined_wifi"),
            ],
        ),

        # ── Ora di dormire ────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="ora di dormire",
                priority=Priority.HIGH,
                cooldown=600,
                actions=[
                    spotify("pause"),
                    arduino("light", 0),
                    arduino("relay", 0),
                    arduino("servo", 0),
                    arduino("rgb", 0x000008),
                    calendar_action("list"),
                ],
            ),
            aliases=["dormo", "vado a letto", "a letto"],
        ),

        # ── Modalità uscita ───────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="modalità uscita",
                priority=Priority.HIGH,
                actions=[
                    arduino("light", 0),
                    arduino("relay", 0),
                    arduino("rgb", 0),
                    arduino("servo", 0),
                    arduino("servo2", 0),
                    Action(tool="arduino", params={"op": "SET", "target": "buzzer2", "melody": "ok"}),
                ],
            ),
            aliases=["uscita"],
        ),

        # ── Allarme ───────────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="allarme",
                priority=Priority.CRITICAL,
                exclusive=True,
                actions=[
                    Action(tool="arduino", params={"op": "SET", "target": "buzzer",  "value": 1}),
                    Action(tool="arduino", params={"op": "SET", "target": "buzzer2", "melody": "alarm"}),
                    Action(tool="arduino", params={"op": "SET", "target": "neopixel","value": 0xFF0000, "effect": 3}),
                ],
            ),
        ),

        # ── Piove ─────────────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="piove",
                priority=Priority.NORMAL,
                cooldown=1800,
                actions=[
                    arduino("servo", 0),
                    arduino("light", 1),
                    arduino("rgb", 0x4488FF),
                    arduino("relay", 1),
                    spotify("search", query="rain lofi study"),
                    weather_action(),
                ],
            ),
            aliases=["sta piovendo", "pioggia"],
            triggers=[
                Trigger(type="context", context={"weather": "rain"}),
            ],
        ),

        # ── Pausa caffè ───────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="pausa caffè",
                priority=Priority.NORMAL,
                cooldown=1200,
                actions=[
                    arduino("relay", 1),
                    arduino("rgb", 0x8B4513),
                    spotify("search", query="espresso morning jazz"),
                    news_action(limit=3),
                    timer_action(3, "Caffè pronto!"),
                ],
            ),
            aliases=["caffe", "caffè", "faccio un caffè"],
        ),

        # ── Cena ──────────────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="cena",
                priority=Priority.NORMAL,
                cooldown=3600,
                actions=[
                    arduino("light", 0),
                    arduino("rgb", 0xFF4400),
                    arduino("relay", 0),
                    arduino("servo", 0),
                    spotify("search", query="cena romantica musica italiana"),
                ],
            ),
            triggers=[
                Trigger(type="time", time="20:00"),
                Trigger(type="context", context={"time_slot": "evening", "presence": "home"}),
            ],
        ),

        # ── Bambini dormono ───────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="bambini dormono",
                priority=Priority.HIGH,
                actions=[
                    spotify("pause"),
                    arduino("light", 0),
                    arduino("relay", 0),
                    arduino("rgb", 0x000003),
                    arduino("servo", 0),
                ],
            ),
            aliases=["bambini a letto"],
        ),

        # ── Weekend mattina ───────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="weekend mattina",
                priority=Priority.LOW,
                cooldown=3600,
                actions=[
                    arduino("light", 0),
                    arduino("rgb", 0xFFCC88),
                    arduino("relay", 0),
                    spotify("search", query="lazy sunday morning playlist"),
                    weather_action(),
                    news_action(limit=5),
                ],
            ),
            aliases=["weekend", "sabato mattina", "domenica mattina"],
        ),

    ]


# ─────────────────────────────────────────────────────────────────────────────
# ISTANZA GLOBALE
# ─────────────────────────────────────────────────────────────────────────────

engine = AutomationEngine()
