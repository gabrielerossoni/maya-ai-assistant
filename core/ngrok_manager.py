"""
Gestione tunnel ngrok.
Estratto da main.py per ridurre la complessità del punto di ingresso.
"""

import subprocess
import sys
import time

import requests


def start_ngrok(port: int) -> str | None:
    """Avvia ngrok in background e ritorna l'URL pubblico."""
    try:
        # Avvia ngrok
        popen_kw: dict = {
            "args": ["ngrok", "http", str(port)],
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        subprocess.Popen(**popen_kw)

        # Aspetta che ngrok sia pronto (max 5s)
        for _ in range(10):
            time.sleep(0.5)
            try:
                res = requests.get("http://127.0.0.1:4040/api/tunnels", timeout=1)
                tunnels = res.json().get("tunnels", [])
                for t in tunnels:
                    if t.get("proto") == "https":
                        return t["public_url"]
            except Exception:
                continue

        return None
    except FileNotFoundError:
        print("[NGROK] ngrok non trovato nel PATH")
        return None
    except Exception as e:
        print(f"[NGROK] Errore: {e}")
        return None
