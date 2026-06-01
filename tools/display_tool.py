"""
tools/display_tool.py
Output visivo del sistema Jarvis.
Mostra stato in tempo reale su terminale separato (o GUI tkinter).
"""

import os
import threading
import time
from datetime import datetime


class DisplayTool:
    """
    Display visivo di Jarvis.
    Versione A: output ASCII animato nel terminale.
    Versione B: GUI tkinter (opzionale).
    """

    def __init__(self):
        self._running = False
        self._thread = None
        self.status = {
            "light": "OFF",
            "servo": "CLOSED",
            "last_cmd": "—",
            "last_reply": "Sistema pronto",
        }

    def initialize(self):
        pass  # nulla da inizializzare

    def start(self):
        """Avvia il display in un thread separato."""
        self._running = True
        self._thread = threading.Thread(target=self._run_display, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def update(self, key: str, value: str):
        """Aggiorna un campo dello stato."""
        self.status[key] = value

    def execute(self, action: dict) -> dict:
        layout = action.get("layout")
        # Collect additional params from top-level keys (excluding tool/layout)
        params = {k: v for k, v in action.items() if k not in ("tool", "layout")}
        if not layout:
            return {"status": "error", "message": "Layout non specificato."}

        # In una configurazione reale, questo potrebbe aggiornare uno stato locale
        # ma qui serve principalmente a far sì che l'AutomationEngine veda l'azione
        # e faccia il broadcast verso la dashboard.
        self.status["last_cmd"] = f"Layout: {layout}"
        return {"status": "ok", "message": f"Layout impostato a {layout}", "layout": layout, "params": params}

    # ── Display ASCII ─────────────────────────

    def _run_display(self):
        """Loop del display ASCII nel terminale (thread separato)."""
        last_status = None
        while self._running:
            current_status = str(self.status)
            if current_status != last_status:
                self._draw()
                last_status = current_status
            time.sleep(0.5)

    def _draw(self):
        """Disegna il pannello di stato."""
        now = datetime.now().strftime("%H:%M:%S")
        s = self.status

        # Usa colori ANSI
        CYAN = "\033[96m"
        GREEN = "\033[92m"
        RED = "\033[91m"
        RESET = "\033[0m"
        BOLD = "\033[1m"

        def color_state(state):
            if state in ("ON", "OPEN"):
                return f"{GREEN}{state}{RESET}"
            return f"{RED}{state}{RESET}"

        panel = f"""
{BOLD}{CYAN}┌─── JARVIS STATUS ─── {now} ───────────────┐{RESET}
│  💡 Luce  : {color_state(s["light"]):<20}              │
│  ⚙  Servo : {color_state(s["servo"]):<20}              │
│                                              │
│  Ultimo cmd : {s["last_cmd"][:35]:<35} │
│  Risposta   : {s["last_reply"][:35]:<35} │
{BOLD}{CYAN}└──────────────────────────────────────────────┘{RESET}"""

        print(panel)


# ══════════════════════════════════════════════
# ALTERNATIVA: GUI TKINTER
# Decommenta per usare la finestra grafica
# ══════════════════════════════════════════════

"""
import tkinter as tk
from tkinter import ttk

class JarvisGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("J.A.R.V.I.S — Control Panel")
        self.root.configure(bg="#0a0a0a")
        self.root.geometry("600x400")
        self._build_ui()

    def _build_ui(self):
        style = ttk.Style()
        style.theme_use("clam")

        title = tk.Label(
            self.root, text="⬡ J.A.R.V.I.S ⬡",
            fg="#00d4ff", bg="#0a0a0a",
            font=("Courier New", 22, "bold")
        )
        title.pack(pady=20)

        self.status_label = tk.Label(
            self.root, text="Sistema pronto",
            fg="#ffffff", bg="#0a0a0a",
            font=("Courier New", 12)
        )
        self.status_label.pack(pady=10)

    def update_status(self, text):
        self.status_label.config(text=text)

    def run(self):
        self.root.mainloop()
"""
