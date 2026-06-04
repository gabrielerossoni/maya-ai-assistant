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

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Callable, Coroutine

from .context_manager import ContextManager, context
from .device_registry import DeviceRegistry, registry

logger = logging.getLogger("maya.automation")


# ─────────────────────────────────────────────────────────────────────────────
# PRIORITÀ
# ─────────────────────────────────────────────────────────────────────────────


class Priority(IntEnum):
    LOW = 10
    NORMAL = 50
    HIGH = 80
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

    tool: str
    params: dict = field(default_factory=dict)
    delay: float = 0.0  # secondi di attesa prima dell'esecuzione
    retry: int = 1  # tentativi in caso di errore
    timeout: float = 5.0  # timeout per tool lenti (es. Arduino seriale)
    background: bool = False  # se True parte dopo il foreground senza bloccare la scena

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


def arduino_batch(actions: list[Action], timeout: float = 3.0) -> Action:
    commands = [a.params.copy() for a in actions if a.tool == "arduino"]
    return Action(tool="arduino", params={"op": "BATCH", "actions": commands}, timeout=timeout)


def arduino_all_off() -> Action:
    return arduino_batch(
        [
            arduino("light", 0),
            arduino("servo", 0),
            arduino("servo2", 0),
            arduino("rgb", 0, effect=0),
            arduino("neopixel", 0, effect=0),
            arduino("buzzer", 0),
            Action(tool="arduino", params={"op": "SET", "target": "buzzer2", "melody": "off"}),
        ],
        timeout=4.0,
    )


def spotify(command: str, **kwargs) -> Action:
    return Action(tool="spotify", params={"command": command, **kwargs})


def background(action: Action) -> Action:
    action.background = True
    return action


def delayed_background(action: Action, delay: float) -> Action:
    action.delay = delay
    action.background = True
    return action


def arduino_melody(melody: str, delay: float = 0.0, background_action: bool = False) -> Action:
    action = Action(tool="arduino", params={"op": "SET", "target": "buzzer2", "melody": melody}, delay=delay)
    action.background = background_action
    return action


def _background_alarm_sequence(duration: float = 20.0, pulse_interval: float = 0.5) -> list[Action]:
    events: list[tuple[float, Action]] = []

    elapsed = pulse_interval
    i = 0
    while elapsed < duration:
        events.append((elapsed, arduino("buzzer", 1 if i % 2 == 0 else 0)))
        elapsed += pulse_interval
        i += 1

    events.extend(
        [
            (duration, arduino("buzzer", 0)),
            (duration, arduino_melody("off")),
            (duration, arduino("neopixel", 0, effect=0)),
        ]
    )

    actions: list[Action] = []
    previous_ts = 0.0
    for ts, action in sorted(events, key=lambda item: item[0]):
        actions.append(delayed_background(action, max(0.0, ts - previous_ts)))
        previous_ts = ts
    return actions


def timer_action(minutes: int, message: str) -> Action:
    return Action(tool="timer", params={"minutes": minutes, "message": message})


def weather_action() -> Action:
    return Action(tool="weather", params={"location": None})


def news_action(limit: int = 3) -> Action:
    return Action(tool="news", params={"limit": limit})


def calendar_action(act: str = "list") -> Action:
    return Action(tool="calendar", params={"action": act})


def display_action(layout: str, delay: float = 0.0, **params) -> Action:
    return Action(tool="display", params={"layout": layout, **params}, delay=delay)


def _background_buzzer_pulse(duration: float = 30.0, interval: float = 0.5) -> list[Action]:
    actions: list[Action] = []
    steps = int(duration / interval)
    for i in range(steps):
        value = 1 if i % 2 == 0 else 0
        actions.append(delayed_background(arduino("buzzer", value), interval))
    actions.append(delayed_background(arduino("buzzer", 0), 0.0))
    return actions


def _background_melody_loop(melody: str, duration: float = 30.0, repeat_every: float = 4.0) -> list[Action]:
    actions: list[Action] = []
    elapsed = repeat_every
    while elapsed < duration:
        actions.append(delayed_background(arduino_melody(melody), repeat_every))
        elapsed += repeat_every
    actions.append(delayed_background(arduino_melody("off"), max(0.0, duration - (elapsed - repeat_every))))
    return actions


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
        import core.automation_engine as _self_module

        return _self_module.context.matches(self.requirements)

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

    type: str = "manual"
    time: str = ""  # "HH:MM" per type="time"
    event_name: str = ""  # nome evento per type="event"
    context: dict = field(default_factory=dict)  # condizioni per type="context"


# ─────────────────────────────────────────────────────────────────────────────
# SCENE — raccolta di azioni con metadati
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Scene:
    """
    Insieme di azioni con nome, condizioni e priorità.
    Sostituisce le liste nel dizionario AUTOMATIONS.
    """

    name: str
    actions: list[Action]
    priority: Priority = Priority.NORMAL
    conditions: list[Condition] = field(default_factory=list)
    exclusive: bool = False  # se True, sospende altre scene attive
    cooldown: float = 0.0  # secondi minimi tra due esecuzioni
    _last_run: float = field(default=0.0, init=False, repr=False)

    def can_run(self, ignore_cooldown: bool = False) -> bool:
        """Verifica condizioni e cooldown."""
        if not ignore_cooldown and time.time() - self._last_run < self.cooldown:
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

    scene: Scene
    triggers: list[Trigger] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    enabled: bool = True
    expires_at: float | None = None  # timestamp Unix, None = permanente
    tags: list[str] = field(default_factory=list)

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

        def phrase_matches(phrase: str) -> bool:
            escaped = re.escape(phrase.lower().strip())
            return bool(re.search(rf"(?<!\w){escaped}(?!\w)", lower))

        if phrase_matches(self.name):
            return True
        return any(phrase_matches(alias) for alias in self.aliases)


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

    # Secondi di grazia dopo l'avvio: i trigger automatici (time/context)
    # vengono ignorati per evitare attivazioni spurie prima che il sistema
    # si sia stabilizzato (es. "piove" che parte subito all'accensione).
    STARTUP_GRACE_SECONDS = float(os.getenv("AUTOMATION_STARTUP_GRACE", "60"))

    def __init__(self, tool_manager=None, memory=None, socket_manager=None, voice_manager=None):
        self._tool_manager = tool_manager
        self.memory = memory
        self.socket_manager = socket_manager
        self.voice_manager = voice_manager
        self._automations: dict[str, Automation] = {}
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._background_tasks: dict[str, set[asyncio.Task]] = {}
        self._scheduler_task: asyncio.Task | None = None
        self.bus = EventBus()
        self._event_log: list[dict] = []  # ultimi N eventi eseguiti
        self._event_subscriptions: dict[tuple[str, str], Callable] = {}
        self.scheduler_interval = float(os.getenv("AUTOMATION_SCHEDULER_INTERVAL", "5"))
        self._scene_lock = asyncio.Lock()
        self._boot_ts: float = time.time()  # timestamp di avvio per grace period

    # ── Registrazione ─────────────────────────────────────────────────────────

    def register(self, automation: Automation):
        """Registra un'automazione nel motore."""
        self._unwire_event_triggers(automation.name)
        self._automations[automation.name] = automation
        self._wire_event_triggers(automation)
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
        self._unwire_event_triggers(name)
        self._automations.pop(name, None)

    def _wire_event_triggers(self, automation: Automation):
        """Collega i Trigger(type='event') all'EventBus interno."""
        for trigger in automation.triggers:
            if trigger.type != "event" or not trigger.event_name:
                continue

            async def _handler(event: str, data: dict, auto_name: str = automation.name):
                current = self._automations.get(auto_name)
                if not current or not current.is_valid():
                    return
                logger.info(f"[ENGINE] Trigger evento: '{auto_name}' ({event})")
                asyncio.create_task(self.execute(current, source=f"event:{event}"))

            self.bus.subscribe(trigger.event_name, _handler)
            self._event_subscriptions[(automation.name, trigger.event_name)] = _handler

    def _unwire_event_triggers(self, automation_name: str):
        """Rimuove eventuali handler event registrati per una automazione."""
        for key, handler in list(self._event_subscriptions.items()):
            name, event_name = key
            if name == automation_name:
                self.bus.unsubscribe(event_name, handler)
                self._event_subscriptions.pop(key, None)

    # ── Risoluzione input → automazione ──────────────────────────────────────

    def resolve(self, user_input: str) -> Automation | None:
        """
        Trova la prima automazione valida che matcha l'input.
        Ordina per priorità decrescente.
        """
        import re

        lower = re.sub(r"\s+", " ", user_input.lower().strip())

        candidates = [a for a in self._automations.values() if a.is_valid() and a.matches_input(lower)]
        if not candidates:
            return None

        return max(candidates, key=lambda a: a.scene.priority)

    def resolve_by_name(self, name: str) -> Automation | None:
        return self._automations.get(name)

    def list_automations(self) -> list[str]:
        return [name for name, a in self._automations.items() if a.is_valid()]

    def _is_manual_source(self, source: str) -> bool:
        return (source or "manual").strip().lower() in {"manual", "voice", "dashboard", "test"}

    def _blocked_reason(self, scene: Scene, ignore_cooldown: bool = False) -> str:
        if not ignore_cooldown and time.time() - scene._last_run < scene.cooldown:
            return "cooldown"
        return "condizioni non soddisfatte"

    def _is_critical_action_error(self, action: Action) -> bool:
        return action.tool in {"arduino", "timer"}

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
        ignore_cooldown = self._is_manual_source(source)

        if not scene.can_run(ignore_cooldown=ignore_cooldown):
            reason = self._blocked_reason(scene, ignore_cooldown=ignore_cooldown)
            logger.info(f"[ENGINE] '{scene.name}' bloccata: {reason}")
            return {"status": "skipped", "reason": reason}

        # Conflict detection: se scene exclusive, cancella altre in esecuzione
        if scene.exclusive and scene.name in self._active_tasks:
            task = self._active_tasks[scene.name]
            if not task.done():
                logger.warning(f"[ENGINE] '{scene.name}' già in esecuzione, skip")
                return {"status": "skipped", "reason": "already_running"}

        logger.info(f"[ENGINE] Esecuzione '{scene.name}' (priorità={scene.priority}, source={source})")

        await self._scene_lock.acquire()
        try:
            if not scene.can_run(ignore_cooldown=ignore_cooldown):
                reason = self._blocked_reason(scene, ignore_cooldown=ignore_cooldown)
                logger.info(f"[ENGINE] '{scene.name}' bloccata: {reason}")
                return {"status": "skipped", "reason": reason}

            results = []
            errors = []
            warnings = []
            conflicts = []
            start_ts = time.time()

            foreground_actions = self._hardware_first([action for action in scene.actions if not action.background])
            background_actions = [action for action in scene.actions if action.background]

            for action in self._compact_arduino_actions(foreground_actions):
                if action.delay > 0:
                    await asyncio.sleep(action.delay)

                action_conflicts = self._detect_action_conflicts(action, scene.name)
                if action_conflicts:
                    conflicts.extend(action_conflicts)
                    conflict = action_conflicts[0]
                    logger.info(
                        f"[ENGINE] Possibile conflitto su {conflict['device']}: "
                        f"{conflict['previous_scene']} -> {scene.name}"
                    )

                result = await self._execute_action_with_retry(action, scene.name)
                results.append(result)

                if result.get("status") == "error":
                    entry = {"action": str(action), "error": result.get("message")}
                    if self._is_critical_action_error(action):
                        errors.append(entry)
                    else:
                        warnings.append(entry)
                    logger.warning(f"[ENGINE] '{scene.name}' — errore in {action}: {result.get('message')}")

                # Aggiorna registry dopo azioni Arduino
                if action.tool == "arduino" and result.get("status") in {"ok", "partial"}:
                    state = result.get("state", {})
                    if state:
                        registry.update_from_arduino_state(state, scene=scene.name)

            if background_actions:
                task = asyncio.create_task(self._execute_background_actions(scene.name, background_actions))
                self._background_tasks.setdefault(scene.name, set()).add(task)
                task.add_done_callback(
                    lambda done_task, name=scene.name: self._background_tasks.get(name, set()).discard(done_task)
                )

            # Aggiorna contesto
            scene.mark_run()
            context.set_scene(scene.name)

            # Sincronizza con la memoria della conversazione (se presente)
            if self.memory:
                await self.memory.add_turn(
                    "system", f"[AUTOMATION] Eseguita automazione '{scene.name}' (source={source})", persist_db=False
                )

            elapsed = round(time.time() - start_ts, 3)
            status = "ok" if not errors else "partial"

            event_entry = {
                "scene": scene.name,
                "source": source,
                "status": status,
                "errors": errors,
                "warnings": warnings,
                "conflicts": conflicts,
                "elapsed": elapsed,
                "ts": start_ts,
            }
            self._log_event(event_entry)

            await self.bus.publish("scene_executed", event_entry)

            logger.info(f"[ENGINE] '{scene.name}' completata in {elapsed}s — status={status}")
            return {
                "status": status,
                "results": results,
                "errors": errors,
                "warnings": warnings,
                "conflicts": conflicts,
                "elapsed": elapsed,
            }
        finally:
            self._scene_lock.release()

    async def execute_by_name(self, name: str, source: str = "manual") -> dict:
        automation = self._automations.get(name)
        if not automation:
            return {"status": "error", "message": f"Automazione '{name}' non trovata"}
        return await self.execute(automation, source=source)

    async def execute_actions(self, actions: list[Action], source: str = "manual") -> list[dict]:
        """Esegui una lista di azioni raw (compatibilità con il vecchio sistema)."""
        results = []
        for action in self._compact_arduino_actions(actions):
            result = await self._execute_action_with_retry(action, source)
            results.append({"tool": action.tool, "result": result})
        return results

    # ── Esecuzione singola azione con retry ───────────────────────────────────

    async def _execute_background_actions(self, scene_name: str, actions: list[Action]):
        try:
            for action in self._compact_arduino_actions(actions):
                if action.delay > 0:
                    await asyncio.sleep(action.delay)
                result = await self._execute_action_with_retry(action, f"{scene_name}:background")
                if result.get("status") == "error":
                    logger.warning(f"[ENGINE] '{scene_name}' background — errore in {action}: {result.get('message')}")
                    msg = (result.get("message") or "").lower()
                    if "arduino not connected" in msg or "arduino non connesso" in msg:
                        # Evita spam infinito: interrompi la sequenza e libera la scena
                        try:
                            self._cancel_background_tasks(scene_name)
                        except Exception:
                            pass
                        try:
                            context.set_scene(None)
                        except Exception:
                            pass
                        break
        except asyncio.CancelledError:
            logger.info(f"[ENGINE] '{scene_name}' background cancellato")
            raise

    def _cancel_background_tasks(self, scene_name: str | None = None):
        names = [scene_name] if scene_name else list(self._background_tasks)
        for name in names:
            for task in list(self._background_tasks.get(name, set())):
                if not task.done():
                    task.cancel()
            self._background_tasks.pop(name, None)

    def _hardware_first(self, actions: list[Action]) -> list[Action]:
        immediate_arduino = [action for action in actions if action.tool == "arduino" and action.delay <= 0]
        arduino_ids = {id(action) for action in immediate_arduino}
        remaining = [action for action in actions if id(action) not in arduino_ids]
        return immediate_arduino + remaining

    def _compact_arduino_actions(self, actions: list[Action]) -> list[Action]:
        compacted: list[Action] = []
        pending: list[Action] = []

        def flush_pending():
            if not pending:
                return
            if len(pending) == 1:
                compacted.append(pending[0])
            else:
                compacted.append(arduino_batch(pending, timeout=max(3.0, sum(a.timeout for a in pending))))
            pending.clear()

        for action in actions:
            if action.tool == "arduino" and action.delay <= 0:
                pending.append(action)
                continue
            flush_pending()
            compacted.append(action)

        flush_pending()
        return compacted

    def _iter_arduino_params(self, action: Action) -> list[dict]:
        if action.tool != "arduino":
            return []
        if action.params.get("op") == "BATCH":
            return [item for item in action.params.get("actions", []) if isinstance(item, dict)]
        return [action.params]

    def _detect_action_conflicts(self, action: Action, scene_name: str) -> list[dict]:
        conflicts = []
        for params in self._iter_arduino_params(action):
            conflict = self._detect_action_conflict(Action(tool="arduino", params=params), scene_name)
            if conflict:
                conflicts.append(conflict)
        return conflicts

    def _detect_action_conflict(self, action: Action, scene_name: str) -> dict | None:
        """Rileva scritture ravvicinate sullo stesso device da scene diverse."""
        if action.tool != "arduino":
            return None
        target = action.params.get("target")
        if not target or "value" not in action.params:
            return None
        entry = registry.get_entry(target)
        if not entry:
            return None
        previous_scene = entry.get("last_set_by")
        if previous_scene == scene_name:
            return None
        if time.time() - entry.get("ts", 0) > 5:
            return None
        new_value = action.params.get("value")
        if entry.get("value") == new_value:
            return None
        return {
            "device": target,
            "previous_scene": previous_scene,
            "previous_value": entry.get("value"),
            "new_value": new_value,
        }

    async def _execute_action_with_retry(self, action: Action, scene_name: str) -> dict:
        if not self._tool_manager:
            return {"status": "error", "message": "ToolManager non configurato"}

        # 0. Check preventivo Spotify: se disabilitato o non connesso, skip immediato
        if action.tool == "spotify":
            enabled = os.environ.get("SPOTIFY_ENABLED", "true").strip().lower() not in ("0", "false", "no")
            if not enabled:
                logger.info(f"[ENGINE] '{scene_name}' — skip Spotify: disabilitato via ENV")
                return {"status": "skipped", "message": "Spotify disabilitato."}

            spotify_tool = self._tool_manager.tools.get("spotify")
            if spotify_tool and not spotify_tool.sp:
                logger.info(f"[ENGINE] '{scene_name}' — skip Spotify: non connesso")
                return {"status": "skipped", "message": "Spotify non connesso."}

        last_result = {}
        for attempt in range(max(1, action.retry)):
            try:
                tool_action = action.to_tool_action()
                result = await asyncio.wait_for(
                    self._tool_manager.execute(tool_action),
                    timeout=action.timeout,
                )

                # --- BROADCAST PER DASHBOARD ---
                if self.socket_manager and result.get("status") == "ok":
                    ws_map = {
                        "weather": "weather",
                        "spotify": "spotify",
                        "calendar": "calendar",
                        "news": "news",
                        "sys_monitor": "stats",
                        "display": "layout",
                    }
                    if action.tool in ws_map:
                        msg_type = ws_map[action.tool]
                        payload = {"type": msg_type}
                        if "data" in result:
                            if isinstance(result["data"], dict):
                                payload.update(result["data"])
                            else:
                                payload["data"] = result["data"]
                        else:
                            payload.update(result)
                        payload.pop("status", None)
                        payload.pop("message", None)
                        await self.socket_manager.broadcast(payload)

                    # Caso speciale Arduino: broadcast stato compatto
                    if action.tool == "arduino":
                        st = result.get("state", {})
                        if st:
                            await self.socket_manager.broadcast(
                                {
                                    "type": "state",
                                    "led": "on" if st.get("light") else "off",
                                    "servo": "open" if (st.get("servo") or 0) > 0 else "0",
                                    "servo2": st.get("servo2", 0),
                                    "rgb1": st.get("rgb1", [0, 0, 0]),
                                    "rgb2": st.get("rgb2", [0, 0, 0]),
                                    "rgb3": st.get("rgb3", [0, 0, 0]),
                                    "buzzer": st.get("buzzer", False),
                                }
                            )

                if result.get("status") != "error":
                    # Opportunistic TTS for certain tools during automations
                    try:
                        if self.voice_manager and os.getenv("MAYA_TTS_AUTOMATIONS", "1").strip().lower() not in (
                            "0",
                            "false",
                            "no",
                        ):
                            if action.tool == "weather" and isinstance(result.get("data"), dict):
                                d = result["data"]
                                loc = d.get("location") or "qui"
                                if scene_name == "piove":
                                    # Annuncia le prossime ore e quando smette
                                    hourly = d.get("hourly") or []
                                    from datetime import datetime

                                    def _fmt_hhmm(tstr: str) -> str:
                                        try:
                                            # Open-Meteo returns ISO times
                                            dt = datetime.fromisoformat(tstr)
                                            h = dt.strftime("%H")
                                            m = dt.strftime("%M")
                                            return h if m == "00" else f"{h}:{m}"
                                        except Exception:
                                            return tstr

                                    if hourly:
                                        # Prendi le prossime ore a partire da ORA (max 12)
                                        now = datetime.now()
                                        _parsed = []
                                        for h in hourly:
                                            ts = h.get("time", "")
                                            try:
                                                dt = datetime.fromisoformat(ts)
                                            except Exception:
                                                dt = None
                                            _parsed.append((dt, h))
                                        next_hours = [h for dt, h in _parsed if (dt is None or dt >= now)][:12]
                                        if not next_hours:
                                            next_hours = [h for _, h in _parsed][:12]
                                        # Trova la prima ora "asciutta"
                                        rainy_codes = {51, 53, 55, 61, 63, 65, 80, 81, 82, 95}
                                        stop_time = None
                                        for h in next_hours:
                                            precip = h.get("precip_mm") or 0
                                            prob = h.get("prob")
                                            code = h.get("code")
                                            is_rainy = (precip and precip > 0.05) or (code in rainy_codes)
                                            if not is_rainy and (prob is None or prob <= 30):
                                                stop_time = _fmt_hhmm(h.get("time", ""))
                                                break
                                        # Crea testo breve
                                        first = next_hours[0]
                                        p0 = int(round(float(first.get("prob") or 0)))
                                        t0 = _fmt_hhmm(first.get("time", ""))
                                        if stop_time:
                                            text = f"Pioggia nelle prossime ore. Probabilità {p0}% alle {t0}. Dovrebbe smettere verso le {stop_time}."
                                        else:
                                            text = f"Pioggia prevista nelle prossime ore. Probabilità {p0}% alle {t0}."
                                        await asyncio.to_thread(self.voice_manager.speak, text)
                                else:
                                    temp = d.get("temp")
                                    _cr = d.get("condition") or ""
                                    cond = _cr.lower()
                                    # Normalizza abbreviazioni con confini di parola per evitare rimpiazzi sovrapposti
                                    subs = [
                                        (r"\bparzialm\.?\b", "parzialmente"),
                                        (r"\bparz\.?\b", "parzialmente"),
                                        (r"\bnuvol\.?\b", "nuvoloso"),
                                        (r"\bposs\.?\b", "possibili"),
                                        (r"\btempor\.?\b", "temporali"),
                                        (r"\bpreval\.?\b", "prevalentemente"),
                                        (r"\bprev\.?\b", "prevalentemente"),
                                    ]
                                    for pat, rep in subs:
                                        cond = re.sub(pat, rep, cond)
                                    parts = []
                                    if temp is not None:
                                        parts.append(f"{int(round(float(temp)))} gradi")
                                    if cond:
                                        parts.append(cond)
                                    if parts:
                                        text = f"Meteo per {loc}: " + ", ".join(parts) + "."
                                        await asyncio.to_thread(self.voice_manager.speak, text)
                            elif action.tool == "news" and isinstance(result.get("news"), list) and result["news"]:
                                titles = [
                                    n.get("title") for n in result["news"] if isinstance(n, dict) and n.get("title")
                                ]
                                if titles:

                                    def _strip_src(t: str) -> str:
                                        i = t.rfind(" - ")
                                        return (t[:i] if i > 0 else t).strip()

                                    first = _strip_src(titles[0])
                                    if len(titles) > 1:
                                        second = _strip_src(titles[1])
                                        text = f"Ultime notizie: {first}. Inoltre, {second}."
                                    else:
                                        text = f"Ultime notizie: {first}."
                                    await asyncio.to_thread(self.voice_manager.speak, text)
                            elif action.tool == "arduino":
                                try:
                                    op = str(action.params.get("op", "")).upper()
                                except Exception:
                                    op = ""
                                if op == "GET":
                                    st = result.get("state", {}) if isinstance(result, dict) else {}
                                    items = []
                                    if isinstance(st.get("light"), bool):
                                        items.append("luce accesa" if st.get("light") else "luce spenta")
                                    sv = st.get("servo")
                                    if isinstance(sv, (int, float)):
                                        items.append("porta aperta" if (sv or 0) > 0 else "porta chiusa")
                                    sv2 = st.get("servo2")
                                    if isinstance(sv2, (int, float)):
                                        items.append("cancello aperto" if (sv2 or 0) > 0 else "cancello chiuso")
                                    t = result.get("temp")
                                    h = result.get("humidity")
                                    if (t is None and h is None) and getattr(self, "_tool_manager", None):
                                        try:
                                            atool = self._tool_manager.tools.get("arduino")
                                            if atool and hasattr(atool, "get_sensor_data"):
                                                sdata = await asyncio.to_thread(atool.get_sensor_data)
                                                if isinstance(sdata, dict):
                                                    t = sdata.get("temp", t)
                                                    h = sdata.get("humidity", h)
                                        except Exception:
                                            pass
                                    if t is not None:
                                        items.append(f"temperatura {int(round(float(t)))} gradi")
                                    if h is not None:
                                        items.append(f"umidità {int(round(float(h)))} percento")
                                    # Sempre saluto per 'sono rientrato'
                                    if scene_name == "sono rientrato":
                                        await asyncio.to_thread(self.voice_manager.speak, "Bentornato!")
                                    if scene_name == "sono rientrato":
                                        # Phrasing più umano usando SOLO dati Arduino
                                        human_parts = []
                                        if t is not None and h is not None:
                                            human_parts.append(
                                                f"In casa ci sono {int(round(float(t)))} gradi e {int(round(float(h)))} percento di umidità"
                                            )
                                        elif t is not None:
                                            human_parts.append(f"In casa ci sono {int(round(float(t)))} gradi")
                                        elif h is not None:
                                            human_parts.append(f"Umidità {int(round(float(h)))} percento")

                                        try:
                                            if isinstance(st.get("light"), bool):
                                                human_parts.append(
                                                    "La luce è accesa" if st.get("light") else "La luce è spenta"
                                                )
                                        except Exception:
                                            pass
                                        try:
                                            if isinstance(sv, (int, float)):
                                                human_parts.append(
                                                    "La porta è aperta" if (sv or 0) > 0 else "La porta è chiusa"
                                                )
                                        except Exception:
                                            pass
                                        try:
                                            if isinstance(sv2, (int, float)):
                                                human_parts.append(
                                                    "Il cancello è aperto" if (sv2 or 0) > 0 else "Il cancello è chiuso"
                                                )
                                        except Exception:
                                            pass

                                        if human_parts:
                                            human_text = ". ".join(human_parts) + "."
                                            await asyncio.to_thread(self.voice_manager.speak, human_text)
                                    elif items:
                                        text = "Stato casa: " + ", ".join(items) + "."
                                        await asyncio.to_thread(self.voice_manager.speak, text)
                    except Exception:
                        pass
                    return result

                last_result = result
                if attempt < action.retry - 1:
                    logger.debug(f"[ENGINE] Retry {attempt + 1}/{action.retry} per {action}")
                    await asyncio.sleep(0.5 * (attempt + 1))
            except asyncio.TimeoutError:
                last_result = {"status": "error", "message": f"timeout ({action.timeout}s)"}
                logger.warning(f"[ENGINE] Timeout su {action} (scena: {scene_name})")
            except Exception as e:
                last_result = {"status": "error", "message": str(e)}
                logger.error(f"[ENGINE] Eccezione su {action}: {e}")

        # Fallback TTS per 'sono rientrato' se il GET status fallisce
        try:
            if self.voice_manager and os.getenv("MAYA_TTS_AUTOMATIONS", "1").strip().lower() not in (
                "0",
                "false",
                "no",
            ):
                try:
                    op = str(action.params.get("op", "")).upper()
                except Exception:
                    op = ""
                if (
                    scene_name == "sono rientrato"
                    and action.tool == "arduino"
                    and op == "GET"
                    and last_result.get("status") == "error"
                ):
                    await asyncio.to_thread(self.voice_manager.speak, "Bentornato!")
        except Exception:
            pass

        return last_result

    # ── Scheduler temporale ───────────────────────────────────────────────────

    def _in_startup_grace(self) -> bool:
        """True se siamo ancora nel periodo di grazia post-avvio."""
        return time.time() - self._boot_ts < self.STARTUP_GRACE_SECONDS

    async def start_scheduler(self):
        """Loop asincrono che controlla trigger temporali e di contesto."""
        logger.info("[ENGINE] Scheduler avviato")
        if self.STARTUP_GRACE_SECONDS > 0:
            logger.info(
                f"[ENGINE] Grace period attivo: trigger automatici sospesi per {self.STARTUP_GRACE_SECONDS:.0f}s"
            )
        while True:
            try:
                # Grace period: salta trigger automatici subito dopo l'avvio
                if self._in_startup_grace():
                    await asyncio.sleep(self.scheduler_interval)
                    continue

                now = datetime.now().strftime("%H:%M")

                for automation in list(self._automations.values()):
                    if not automation.is_valid():
                        continue

                    for trigger in automation.triggers:
                        if trigger.type == "time" and trigger.time == now:
                            # Evita esecuzioni multiple nello stesso minuto
                            last = automation.scene._last_run
                            if time.time() - last > 59:
                                logger.info(f"[SCHEDULER] Trigger temporale: '{automation.name}' ({now})")
                                asyncio.create_task(self.execute(automation, source=f"scheduler:{now}"))

                        elif trigger.type == "context" and trigger.context:
                            if context.matches(trigger.context):
                                last = automation.scene._last_run
                                if time.time() - last > 300:  # max ogni 5 min per context trigger
                                    logger.info(f"[SCHEDULER] Trigger contesto: '{automation.name}'")
                                    asyncio.create_task(self.execute(automation, source="context_trigger"))

            except Exception as e:
                logger.error(f"[SCHEDULER] Errore: {e}")

            await asyncio.sleep(self.scheduler_interval)

    # ── Event log ─────────────────────────────────────────────────────────────

    def _log_event(self, entry: dict):
        self._event_log.append(entry)
        if len(self._event_log) > 200:
            self._event_log = self._event_log[-200:]

    def get_event_log(self, limit: int = 20) -> list[dict]:
        return self._event_log[-limit:]

    def get_last_scene(self) -> str | None:
        return context.get("active_scene")

    async def clear_active_scene(self) -> dict:
        """Disattiva la scena corrente e porta tutti gli attuatori in OFF."""
        previous = context.get("active_scene")
        self._cancel_background_tasks(previous)
        results = []
        errors = []
        # doppio tentativo: se Arduino si è appena disconnesso, aspetta un attimo
        result = await self._execute_action_with_retry(arduino_all_off(), "scene_off")
        if result.get("status") == "error" and "Arduino not connected" in result.get("message", ""):
            await asyncio.sleep(0.8)
            result = await self._execute_action_with_retry(arduino_all_off(), "scene_off")
        results.append(result)
        if result.get("status") == "error":
            errors.append({"action": "arduino_all_off", "error": result.get("message")})
        elif result.get("state"):
            registry.update_from_arduino_state(result["state"], scene="scene_off")
        context.set_scene(None)
        status = "ok" if not errors else "partial"
        self._log_event(
            {"scene": previous, "source": "manual", "status": "cleared", "errors": errors, "ts": time.time()}
        )
        return {"status": status, "previous": previous, "results": results, "errors": errors}


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
                    spotify("pause"),
                    arduino("light", 0),
                    arduino("servo", 0),
                    arduino("brightness", 32),
                    arduino("rgb", {"r": 0, "g": 0, "b": 16}),
                    calendar_action("list"),
                ],
            ),
            aliases=[
                "buona notte",
                "bonne nuit",
                "notte",
                "modalità notte",
                "modalita notte",
                "modo notte",
                "vado a dormire",
                "va a dormire",
                "dormo",
                "vado a letto",
                "a letto",
                "ora di dormire",
            ],
            triggers=[
                Trigger(type="time", time="23:00"),
                Trigger(type="time", time="23:30"),
                Trigger(type="context", context={"time_slot": "night", "presence": "home"}),
            ],
        ),
        # ── Buongiorno ────────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="buongiorno",
                priority=Priority.HIGH,
                cooldown=60,
                actions=[
                    arduino("light", 1),
                    arduino("rgb", {"r": 255, "g": 213, "b": 128}),
                    arduino("servo", 0),
                    display_action("news"),
                    news_action(limit=5),
                    display_action("weather"),
                    weather_action(),
                    display_action("orb", exitAfter=True),
                    display_action("orb", delay=4),
                    background(spotify("search", query="buongiorno playlist mattina")),
                    background(calendar_action("list")),
                ],
            ),
            aliases=["buon giorno", "morning"],
            triggers=[
                Trigger(type="time", time="07:00"),
            ],
        ),
        # ── Sveglia ───────────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="sveglia",
                priority=Priority.CRITICAL,
                actions=[
                    arduino("light", 1),
                    arduino("rgb", {"r": 255, "g": 213, "b": 128}, effect=1),
                    arduino("buzzer", 1),
                    arduino_melody("wake_radar"),
                    *_background_melody_loop("wake_radar", duration=30.0, repeat_every=4.0),
                    delayed_background(arduino("rgb", 0, effect=0), 0.0),
                    delayed_background(arduino("buzzer", 0), 0.0),
                    spotify("search", query="energetic morning wake up"),
                ],
            ),
            aliases=["svegliami", "dammi la sveglia"],
        ),
        # ── Modalità film ─────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="modalità film",
                priority=Priority.NORMAL,
                exclusive=True,
                actions=[
                    arduino("light", 0),
                    arduino("rgb1", {"r": 34, "g": 0, "b": 0}),
                    arduino("rgb2", {"r": 34, "g": 0, "b": 0}),
                    arduino("rgb3", 0),
                ],
            ),
            aliases=["film", "cinema", "guardo un film"],
        ),
        # ── Modalità relax ────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="modalità relax",
                priority=Priority.LOW,
                actions=[
                    arduino("light", 0),
                    arduino("rgb1", {"r": 68, "g": 0, "b": 85}),
                    arduino("rgb2", {"r": 68, "g": 0, "b": 85}),
                    arduino("rgb3", 0),
                ],
            ),
            aliases=["relax"],
        ),
        # ── Ospiti in arrivo ──────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="ospiti in arrivo",
                priority=Priority.HIGH,
                cooldown=120,
                actions=[
                    arduino("light", 1),
                    arduino("rgb", {"r": 255, "g": 255, "b": 255}),
                    arduino("servo", 90),
                    arduino("servo2", 90),
                    arduino_melody("startup"),
                ],
            ),
            aliases=["ospite", "modalità ospite", "arrivano ospiti", "stanno arrivando"],
        ),
        # ── Vado fuori ────────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="vado fuori",
                priority=Priority.HIGH,
                cooldown=30,
                actions=[
                    arduino("light", 0),
                    arduino("rgb", 0),
                    arduino("servo", 0),
                    arduino("servo2", 0),
                    arduino_melody("ok"),
                    spotify("pause"),
                    weather_action(),
                ],
            ),
            aliases=["esco", "me ne vado", "vado via", "uscita", "modalità uscita"],
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
                    arduino("rgb", {"r": 255, "g": 140, "b": 66}),
                    Action(tool="arduino", params={"op": "GET", "target": "status"}, delay=0.2, retry=2, timeout=1.5),
                    spotify("search", query="relax after work playlist"),
                    timer_action(5, "Ricordati di chiudere la porta!"),
                ],
            ),
            aliases=["sono tornato", "rientro", "torno"],
            triggers=[
                Trigger(type="event", event_name="phone_joined_wifi"),
            ],
        ),
        # ── Allarme ───────────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="allarme",
                priority=Priority.CRITICAL,
                exclusive=True,
                actions=[
                    arduino("neopixel", {"r": 255, "g": 0, "b": 0}, effect=3),
                    arduino("buzzer", 1),
                    arduino_melody("alarm"),
                    *_background_alarm_sequence(duration=20.0, pulse_interval=0.5),
                ],
            ),
            aliases=["alarme", "all'armi", "allarmi"],
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
                    arduino("rgb", {"r": 68, "g": 136, "b": 255}),
                    spotify("search", query="rain lofi study"),
                    weather_action(),
                ],
            ),
            aliases=["sta piovendo", "pioggia"],
            triggers=[
                Trigger(type="context", context={"weather": "rain"}),
            ],
        ),
        # ── Cena ──────────────────────────────────────────────────────────────
        Automation(
            scene=Scene(
                name="cena",
                priority=Priority.NORMAL,
                cooldown=3600,
                actions=[
                    arduino("light", 0),
                    arduino("rgb1", {"r": 255, "g": 140, "b": 66}),
                    arduino("rgb2", {"r": 255, "g": 140, "b": 66}),
                    arduino("rgb3", 0),
                    arduino("servo", 0),
                    spotify("search", query="cena romantica musica italiana"),
                ],
            ),
            triggers=[
                Trigger(type="time", time="20:00"),
                Trigger(type="context", context={"time_slot": "evening", "presence": "home"}),
            ],
        ),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# ISTANZA GLOBALE
# ─────────────────────────────────────────────────────────────────────────────

engine = AutomationEngine()
