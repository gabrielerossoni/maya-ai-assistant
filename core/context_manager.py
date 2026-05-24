"""
context_manager.py - Stato globale della casa e del contesto utente.

Tiene traccia di: orario, presenza, meteo, attività, modalità attiva,
dispositivi online/offline. Thread-safe, persistente su disco.
"""

import json
import os
import time
from datetime import datetime
from threading import RLock
from typing import Any

_STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "context_state.json")


class ContextManager:
    """
    Singleton che mantiene lo stato contestuale della casa.
    
    context = {
        "time_slot":    "morning" | "afternoon" | "evening" | "night",
        "presence":     "home" | "away" | "unknown",
        "weather":      "clear" | "rain" | "cloud" | "snow" | "unknown",
        "activity":     "idle" | "working" | "gaming" | "sleeping" | "eating" | str,
        "active_scene": str | None,
        "devices":      { "arduino": "online" | "offline", ... },
        "flags":        { "guests": bool, "children_sleeping": bool, ... },
        "last_updated": float,
    }
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._lock = RLock()
            cls._instance._state: dict = {}
            cls._instance._load()
        return cls._instance

    # ── Persistenza ───────────────────────────────────────────────────────────

    def _default_state(self) -> dict:
        return {
            "time_slot":    self._compute_time_slot(),
            "presence":     "unknown",
            "weather":      "unknown",
            "activity":     "idle",
            "active_scene": None,
            "devices":      {},
            "flags":        {"guests": False, "children_sleeping": False},
            "last_updated": time.time(),
        }

    def _load(self):
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        try:
            with open(_STATE_PATH, "r", encoding="utf-8") as f:
                self._state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._state = self._default_state()
        # Reset campi volatili per evitare trigger su dati stale di sessioni precedenti
        self._state["weather"] = "unknown"
        self._state["presence"] = "unknown"
        self._state["time_slot"] = self._compute_time_slot()

    def _save(self):
        try:
            with open(_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(self._state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[CONTEXT] Errore salvataggio stato: {e}")

    # ── Lettura ───────────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._state.get(key, default)

    def snapshot(self) -> dict:
        """Ritorna una copia immutabile dello stato corrente."""
        with self._lock:
            self._state["time_slot"] = self._compute_time_slot()
            return dict(self._state)

    # ── Scrittura ─────────────────────────────────────────────────────────────

    def set(self, key: str, value: Any, persist: bool = True):
        with self._lock:
            self._state[key] = value
            self._state["last_updated"] = time.time()
            if persist:
                self._save()

    def set_scene(self, scene_name: str | None):
        self.set("active_scene", scene_name)

    def set_presence(self, presence: str):
        """presence: 'home' | 'away'"""
        self.set("presence", presence)

    def set_weather(self, condition: str):
        """condition: 'clear' | 'rain' | 'cloud' | 'snow'"""
        self.set("weather", condition)

    def set_activity(self, activity: str):
        self.set("activity", activity)

    def set_flag(self, flag: str, value: bool):
        with self._lock:
            self._state.setdefault("flags", {})[flag] = value
            self._state["last_updated"] = time.time()
            self._save()

    def set_device_status(self, device: str, status: str):
        """status: 'online' | 'offline'"""
        with self._lock:
            self._state.setdefault("devices", {})[device] = status
            self._state["last_updated"] = time.time()
            self._save()

    # ── Utilità ───────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_time_slot() -> str:
        h = datetime.now().hour
        if 6 <= h < 12:
            return "morning"
        elif 12 <= h < 18:
            return "afternoon"
        elif 18 <= h < 23:
            return "evening"
        else:
            return "night"

    def matches(self, conditions: dict) -> bool:
        """
        Verifica se il contesto corrente soddisfa un dizionario di condizioni.
        
        Esempio:
            ctx.matches({"time_slot": "night", "presence": "home"})
        
        Supporta:
            - valore singolo: {"presence": "home"}
            - lista OR: {"time_slot": ["evening", "night"]}
            - negazione: {"presence": {"not": "away"}}
        """
        snap = self.snapshot()
        for key, expected in conditions.items():
            actual = snap.get(key)
            if isinstance(expected, list):
                if actual not in expected:
                    return False
            elif isinstance(expected, dict) and "not" in expected:
                if actual == expected["not"]:
                    return False
            else:
                if actual != expected:
                    return False
        return True

    def __repr__(self) -> str:
        s = self.snapshot()
        return (
            f"Context(scene={s.get('active_scene')}, "
            f"time={s.get('time_slot')}, presence={s.get('presence')}, "
            f"weather={s.get('weather')}, activity={s.get('activity')})"
        )


# Istanza globale singleton
context = ContextManager()
