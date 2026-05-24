"""
Gestione avvio e connessione Ollama.
Estratto da main.py per ridurre la complessità del punto di ingresso.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "127.0.0.1")
OLLAMA_PORT = int(os.environ.get("OLLAMA_PORT", "11434"))


def _ollama_addr() -> tuple[str, int]:
    host = OLLAMA_HOST
    if host.startswith("http://"):
        host = host[7:]
    elif host.startswith("https://"):
        host = host[8:]
    host = host.split("/")[0]
    if ":" in host:
        h, _, p = host.partition(":")
        try:
            return h, int(p)
        except ValueError:
            return h, OLLAMA_PORT
    return host, OLLAMA_PORT


async def _ollama_api_reachable(timeout: float = 0.75) -> bool:
    """Versione non-bloccante del check raggiungibilità Ollama."""

    def _check():
        host, port = _ollama_addr()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    return await asyncio.to_thread(_check)


def _resolve_ollama_executable() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    if sys.platform == "win32":
        local = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Programs",
            "Ollama",
            "ollama.exe",
        )
        if os.path.isfile(local):
            return local
    return None


def ensure_ollama_running(max_wait_sec: int = 45) -> None:
    """
    Se l'API Ollama non risponde, prova ad avviare `ollama serve` in background.
    Disabilita con MAYA_SKIP_OLLAMA_AUTOSTART=1 oppure se OLLAMA_HOST punta a un host remoto.
    """
    if os.environ.get("OLLAMA_ENABLED", "true").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        print("[OLLAMA] Disabilitato tramite OLLAMA_ENABLED=false")
        return

    if os.environ.get("MAYA_SKIP_OLLAMA_AUTOSTART", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return

    host, _ = _ollama_addr()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return

    # Check sync reachable (using socket directly)
    def _check_sync():
        host, port = _ollama_addr()
        try:
            with socket.create_connection((host, port), timeout=0.75):
                return True
        except OSError:
            return False

    if _check_sync():
        return

    ollama_exe = _resolve_ollama_executable()
    if not ollama_exe:
        print("[OLLAMA] Eseguibile non trovato. Installa Ollama da https://ollama.com oppure avvialo manualmente.")
        return

    print("[OLLAMA] Avvio del server locale in background...")
    popen_kw: dict = {
        "args": [ollama_exe, "serve"],
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        subprocess.Popen(**popen_kw)
    except OSError as e:
        print(f"[OLLAMA] Impossibile avviare ollama serve: {e}")
        return

    for i in range(max_wait_sec):
        if _check_sync():
            print("[OLLAMA] Server pronto.")
            return
        time.sleep(1)
        if i in (4, 14) and i > 0:
            print("[OLLAMA] Ancora in attesa del servizio...")

    print(
        "[OLLAMA] Timeout: il servizio non risponde. Avvia l'app Ollama o "
        "`ollama serve` da terminale, poi rilancia MAYA."
    )
