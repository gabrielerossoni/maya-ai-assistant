"""
memory_manager.py
Gestisce la memoria delle conversazioni di Jarvis.
Salva su JSON locale, fornisce contesto all'LLM.
"""

import json
import os
from datetime import datetime

MEMORY_FILE = "data/memory.json"
MAX_TURNS = 10  # quanti turni di conversazione tenere in memoria


class MemoryManager:
    """Memoria a breve termine + persistente del sistema Jarvis."""

    def __init__(self):
        self.turns = []  # [{"role": "user"|"jarvis", "text": "...", "time": "..."}]

    def load(self):
        """Carica memoria da file JSON."""
        os.makedirs("data", exist_ok=True)
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.turns = data.get("turns", [])
                print(f"[MEMORY] {len(self.turns)} turni caricati dalla memoria.")
        else:
            self.turns = []

    def save(self):
        """Salva memoria su file JSON."""
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump({"turns": self.turns}, f, ensure_ascii=False, indent=2)

    def add_turn(self, role: str, text: str):
        """Aggiunge un turno alla memoria."""
        self.turns.append(
            {
                "role": role,
                "text": text,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        # Tieni solo gli ultimi MAX_TURNS turni
        if len(self.turns) > MAX_TURNS:
            self.turns = self.turns[-MAX_TURNS:]

    def get_context(self) -> str:
        """
        Restituisce il contesto delle ultime conversazioni
        da inserire nel prompt LLM.
        """
        if not self.turns:
            return ""

        lines = ["Conversazione recente:"]
        for t in self.turns[-6:]:  # ultimi 6 turni nel prompt
            role = "Utente" if t["role"] == "user" else "JARVIS"
            lines.append(f"{role}: {t['text']}")

        return "\n".join(lines) + "\n"

    def clear(self):
        """Svuota la memoria."""
        self.turns = []
        self.save()
        print("[MEMORY] Memoria cancellata.")

    def summary(self) -> str:
        """Restituisce un riassunto della memoria."""
        return f"{len(self.turns)} turni in memoria (max {MAX_TURNS})"
