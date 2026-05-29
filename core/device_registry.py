"""
device_registry.py - Registro persistente dello stato dei dispositivi.

Tiene traccia dell'ultimo stato noto di ogni dispositivo fisico (luci,
servo, RGB, buzzer, ecc.). Permette conflict detection e rollback.
"""

from __future__ import annotations

import json
import os
import time
from threading import RLock
from typing import Any

_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "device_registry.json")


class DeviceRegistry:
    """
    Registro centralizzato di tutti i dispositivi.

    Struttura interna:
    {
        "light":   { "value": False, "last_set_by": "buonanotte", "ts": 1716000000 },
        "servo":   { "value": 0,     "last_set_by": "modalità uscita", "ts": ... },
        "rgb":     { "value": [0,0,0], ... },
        "buzzer":  { "value": False, ... },
        ...
    }
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._lock = RLock()
            cls._instance._devices: dict = {}
            cls._instance._load()
        return cls._instance

    def _load(self):
        os.makedirs(os.path.dirname(_REGISTRY_PATH), exist_ok=True)
        try:
            with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
                self._devices = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._devices = {}

    def _save(self):
        try:
            with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
                json.dump(self._devices, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[REGISTRY] Errore salvataggio: {e}")

    # ── API pubblica ──────────────────────────────────────────────────────────

    def update(self, device: str, value: Any, scene: str = "manual"):
        """Aggiorna lo stato di un dispositivo con traccia della sorgente."""
        with self._lock:
            self._devices[device] = {
                "value": value,
                "last_set_by": scene,
                "ts": time.time(),
            }
            self._save()

    def get_value(self, device: str, default: Any = None) -> Any:
        with self._lock:
            entry = self._devices.get(device)
            return entry["value"] if entry else default

    def get_entry(self, device: str) -> dict | None:
        with self._lock:
            return dict(self._devices[device]) if device in self._devices else None

    def snapshot(self) -> dict:
        """Snapshot completo: {device: {value, last_set_by, ts}}"""
        with self._lock:
            return {k: dict(v) for k, v in self._devices.items()}

    def get_current_values(self) -> dict:
        """Ritorna solo i valori: {device: value}"""
        with self._lock:
            return {k: v["value"] for k, v in self._devices.items()}

    def update_from_arduino_state(self, state: dict, scene: str = "hardware"):
        """
        Aggiorna il registro da uno stato Arduino ricevuto via seriale.
        state = {"light": False, "servo": 0, "rgb1": [0,0,0], ...}
        """
        for device, value in state.items():
            self.update(device, value, scene=scene)

    def check_conflict(self, device: str, new_value: Any, min_age_seconds: float = 5.0) -> bool:
        """
        Ritorna True se il dispositivo è stato modificato recentemente
        da un'altra scena (potenziale conflitto).
        """
        with self._lock:
            entry = self._devices.get(device)
            if not entry:
                return False
            age = time.time() - entry.get("ts", 0)
            return age < min_age_seconds


# Istanza globale singleton
registry = DeviceRegistry()
