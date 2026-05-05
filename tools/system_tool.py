"""
tools/system_tool.py
Esegue comandi sul sistema operativo locale.
"""

import subprocess
import platform
import os


class SystemTool:
    """Tool per comandi OS: aprire app, screenshot, spegnimento, ecc."""

    def initialize(self):
        self.os = platform.system()  # "Windows", "Linux", "Darwin"
        print(f"[SYSTEM] OS rilevato: {self.os}")

    def execute(self, action: dict) -> dict:
        """
        Esegue un comando di sistema.
        action: {"tool": "system", "command": "shutdown"}
        """
        command = action.get("command", "").lower().strip()

        # Mappa comandi → funzioni
        dispatch = {
            "shutdown":        self._shutdown,
            "open_browser":    self._open_browser,
            "open_spotify":    self._open_spotify,
            "screenshot":      self._screenshot,
            "open_notepad":    self._open_notepad,
            "volume_up":       self._volume_up,
            "volume_down":     self._volume_down,
            "lock_screen":     self._lock_screen,
        }

        handler = dispatch.get(command)
        if handler is None:
            return {"status": "error", "message": f"Comando '{command}' non riconosciuto"}

        try:
            result = handler()
            return {"status": "ok", "command": command, "detail": result}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ── Implementazioni ───────────────────────

    def _shutdown(self):
        print("[SYSTEM] Spegnimento PC tra 30 secondi... (usa 'shutdown /a' per annullare)")
        if self.os == "Windows":
            subprocess.Popen(["shutdown", "/s", "/t", "30"])
        else:
            subprocess.Popen(["shutdown", "-h", "+1"])
        return "shutdown avviato"

    def _open_browser(self):
        if self.os == "Windows":
            os.startfile("https://www.google.com")
        elif self.os == "Darwin":
            subprocess.Popen(["open", "https://www.google.com"])
        else:
            subprocess.Popen(["xdg-open", "https://www.google.com"])
        return "browser aperto"

    def _open_spotify(self):
        if self.os == "Windows":
            subprocess.Popen(["spotify"])
        elif self.os == "Darwin":
            subprocess.Popen(["open", "-a", "Spotify"])
        else:
            subprocess.Popen(["spotify"])
        return "spotify aperto"

    def _screenshot(self):
        try:
            import pyautogui
            # Get the correct Desktop path on Windows
            desktop = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop') if self.os == "Windows" else os.path.expanduser("~/Desktop")
            path = os.path.join(desktop, "jarvis_screenshot.png")
            pyautogui.screenshot(path)
            return f"screenshot salvato in {path}"
        except ImportError:
            return "Libreria 'pyautogui' non installata. Installa con: pip install pyautogui"
        except Exception as e:
            return f"Errore durante lo screenshot: {e}"

    def _open_notepad(self):
        if self.os == "Windows":
            subprocess.Popen(["notepad"])
        else:
            subprocess.Popen(["gedit"])
        return "editor aperto"

    def _volume_up(self):
        try:
            import keyboard
            keyboard.press_and_release('volume up')
            return "volume aumentato"
        except ImportError:
            return "keyboard non installato"

    def _volume_down(self):
        try:
            import keyboard
            keyboard.press_and_release('volume down')
            return "volume diminuito"
        except ImportError:
            return "keyboard non installato"

    def _lock_screen(self):
        if self.os == "Windows":
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        elif self.os == "Linux":
            subprocess.Popen(["gnome-screensaver-command", "-l"])
        return "schermo bloccato"
