"""
tools/system_tool.py
Esegue comandi sul sistema operativo locale.
"""

import os
import platform
import subprocess


class SystemTool:
    """Tool per comandi OS: aprire app, screenshot, spegnimento, ecc."""

    def initialize(self):
        self.os = platform.system()  # "Windows", "Linux", "Darwin"

    def execute(self, action: dict) -> dict:
        """
        Esegue un comando di sistema.
        action: {"tool": "system", "command": "shutdown"}
        """
        command = action.get("command", "").lower().strip()

        # Mappa comandi → funzioni
        dispatch = {
            "shutdown": self._shutdown,
            "open_browser": self._open_browser,
            "open_spotify": self._open_spotify,
            "screenshot": self._screenshot,
            "open_notepad": self._open_notepad,
            "volume_up": self._volume_up,
            "volume_down": self._volume_down,
            "lock_screen": self._lock_screen,
            "stats": self._stats,
            "sys_monitor": self._stats,
            "status": self._stats,
        }

        handler = dispatch.get(command)
        if handler is None:
            return {"status": "error", "message": f"Comando '{command}' non riconosciuto"}

        try:
            result = handler()
            res = {"status": "ok", "command": command, "detail": result}
            if isinstance(result, dict) and "message" in result:
                res["message"] = result["message"]
            if isinstance(result, dict) and "data" in result:
                res["data"] = result["data"]
            return res
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ── Implementazioni ───────────────────────

    def _stats(self):
        import psutil

        from core.gpu_stats import get_gpu_stats

        cpu_usage = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        ram_usage = ram.percent
        ram_total = ram.total / (1024**3)  # in GB
        ram_used = ram.used / (1024**3)  # in GB

        gpu_stats = get_gpu_stats()
        msg = f"Utilizzo CPU: {cpu_usage}%\nUtilizzo RAM: {ram_usage}% ({ram_used:.1f}GB su {ram_total:.1f}GB)"
        if gpu_stats.get("gpu_available"):
            gpu_name = gpu_stats.get("gpu_name") or "GPU"
            msg += f"\nUtilizzo {gpu_name}: {gpu_stats['gpu']}%"
        else:
            msg += "\nGPU: non rilevata"

        return {"message": msg, "data": gpu_stats}

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
            desktop = (
                os.path.join(os.path.join(os.environ["USERPROFILE"]), "Desktop")
                if self.os == "Windows"
                else os.path.expanduser("~/Desktop")
            )
            path = os.path.join(desktop, "maya_screenshot.png")
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

            keyboard.press_and_release("volume up")
            return "volume aumentato"
        except ImportError:
            return "keyboard non installato"

    def _volume_down(self):
        try:
            import keyboard

            keyboard.press_and_release("volume down")
            return "volume diminuito"
        except ImportError:
            return "keyboard non installato"

    def _lock_screen(self):
        if self.os == "Windows":
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
        elif self.os == "Linux":
            subprocess.Popen(["gnome-screensaver-command", "-l"])
        return "schermo bloccato"
