"""
preference_learner.py - Apprendimento preferenze utente dall'uso.
Osserva comandi e automazioni per costruire un profilo comportamentale.
Niente ML: pattern matching statistico semplice e affidabile.
"""

import json
import os
from datetime import datetime

PREFS_FILE = os.path.join("data", "user_preferences.json")

_KNOWN_SCENES = [
    "modalità film",
    "buonanotte",
    "modalità studio",
    "modalità relax",
    "modalità notte",
    "modalità lavoro",
    "modalità lettura",
]


class PreferenceLearner:
    """
    Osserva i comandi e le automazioni attivate per costruire
    un profilo comportamentale dell'utente.
    """

    def __init__(self):
        self.prefs = self._load()

    def _load(self) -> dict:
        if os.path.exists(PREFS_FILE):
            try:
                with open(PREFS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "scene_frequency": {},
            "active_hours": {},
            "tool_frequency": {},
            "last_updated": None,
        }

    def _save(self):
        self.prefs["last_updated"] = datetime.now().isoformat()
        os.makedirs("data", exist_ok=True)
        try:
            with open(PREFS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.prefs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[PREFS] Errore salvataggio preferenze: {e}")

    def observe_command(self, user_input: str, actions_executed: list):
        """Chiamato dopo ogni esecuzione di comando."""
        hour = str(datetime.now().hour)
        self.prefs["active_hours"][hour] = self.prefs["active_hours"].get(hour, 0) + 1

        lower = user_input.lower()

        # Traccia scene attivate
        for scene in _KNOWN_SCENES:
            if scene in lower:
                self.prefs["scene_frequency"][scene] = (
                    self.prefs["scene_frequency"].get(scene, 0) + 1
                )

        # Traccia frequenza tool
        for action in actions_executed:
            tool = action.get("tool", "")
            if tool and tool != "none":
                self.prefs["tool_frequency"][tool] = (
                    self.prefs["tool_frequency"].get(tool, 0) + 1
                )

        self._save()

    def get_context_injection(self) -> str:
        """
        Ritorna una stringa di contesto da iniettare nel system prompt.
        Vuota se non ci sono ancora preferenze significative.
        """
        lines = []

        # Scene più usate (almeno 2 attivazioni)
        frequent_scenes = [
            (s, n)
            for s, n in self.prefs.get("scene_frequency", {}).items()
            if n >= 2
        ]
        if frequent_scenes:
            top = sorted(frequent_scenes, key=lambda x: x[1], reverse=True)[:3]
            scenes_str = ", ".join(f"'{s}' ({n}x)" for s, n in top)
            lines.append(f"Scene preferite: {scenes_str}.")

        # Orari più attivi
        active = self.prefs.get("active_hours", {})
        if active:
            top_hours = sorted(active.items(), key=lambda x: x[1], reverse=True)[:2]
            hours_str = ", ".join(f"{h}:00" for h, _ in top_hours)
            lines.append(f"Orari più attivi: {hours_str}.")

        # Tool più usati
        tool_freq = self.prefs.get("tool_frequency", {})
        if tool_freq:
            top_tools = sorted(tool_freq.items(), key=lambda x: x[1], reverse=True)[:3]
            tools_str = ", ".join(f"{t} ({n}x)" for t, n in top_tools)
            lines.append(f"Tool più utilizzati: {tools_str}.")

        return "\n".join(lines)
