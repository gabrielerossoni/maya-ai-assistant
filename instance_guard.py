"""
Istanza unica: PID file + bind su porta locale dedicata (il socket evita stale lock dopo crash).
Bypass: MAYA_SKIP_INSTANCE_GUARD=1
"""

from __future__ import annotations

import atexit
import os
import signal
import socket
import sys
import tempfile


def pid_file_path() -> str:
    """Percorso cross-platform fuori dai binari del progetto."""
    root = (
        os.environ.get("MAYA_RUNTIME_DIR") or tempfile.gettempdir()
    ).rstrip(os.sep)
    return os.path.join(root, "maya.pid")


PID_FILE = pid_file_path()
LOCK_PORT = int(os.environ.get("MAYA_LOCK_PORT", "47200"))


class InstanceGuard:
    def __init__(self) -> None:
        self._lock_socket: socket.socket | None = None

    def acquire(self) -> bool:
        if not self._try_socket_lock():
            return False
        self._write_pid()
        return True

    def release(self) -> None:
        if self._lock_socket is not None:
            try:
                self._lock_socket.close()
            except OSError:
                pass
            self._lock_socket = None
        try:
            if os.path.isfile(PID_FILE):
                os.remove(PID_FILE)
        except OSError:
            pass

    def _try_socket_lock(self) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # SO_REUSEADDR=0: altra istanza attiva blocca davvero il bind sulla LOCK_PORT.
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        except OSError:
            pass
        try:
            s.bind(("127.0.0.1", LOCK_PORT))
            s.listen(1)
            self._lock_socket = s
            return True
        except OSError:
            s.close()
            return False

    def _write_pid(self) -> None:
        tmp = PID_FILE + ".tmp"
        with open(tmp, "w", encoding="ascii") as f:
            f.write(str(os.getpid()))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, PID_FILE)


def kill_existing() -> bool:
    """
    Legge il PID file e tenta terminazione graceful del processo.
    Ritorna True se aveva tentato terminazione utilizzabile; False solo se nothing to do/cleanup-only.
    """
    import psutil

    if not os.path.isfile(PID_FILE):
        print(f"[KILL] Nessun PID file ({PID_FILE}); niente da fermare tramite questo meccanismo.")
        print(f"[KILL] Se porta {LOCK_PORT} è occupata, è un altro uso di quella porta o istanza senza PID file.")
        return False

    with open(PID_FILE, encoding="ascii") as f:
        raw = f.read().strip()
    try:
        if not raw:
            raise ValueError("PID file vuoto")
        pid = int(raw)
        if pid <= 0:
            raise ValueError("PID non positivo")
    except ValueError as e:
        preview = raw if raw else "(vuoto)"
        print(
            f"[KILL] PID file non valido ({PID_FILE}): contenuto malformato ({preview!r}) "
            f"— {e}. Rimuovo il file."
        )
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return False

    if not psutil.pid_exists(pid):
        print(f"[KILL] PID {pid} non esiste più, rimuovo stale PID file.")
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return False

    proc = psutil.Process(pid)
    print(f"[KILL] Termino PID {pid} ({proc.name()})…")
    try:
        proc.terminate()
        proc.wait(timeout=8)
        print("[KILL] Processo terminato.")
    except psutil.TimeoutExpired:
        proc.kill()
        print("[KILL] Processo killato (hard).")
    except psutil.NoSuchProcess:
        pass

    try:
        if os.path.isfile(PID_FILE):
            os.remove(PID_FILE)
    except OSError:
        pass
    return True


def skip_guard() -> bool:
    return os.environ.get("MAYA_SKIP_INSTANCE_GUARD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def install_signal_handlers(guard: InstanceGuard) -> None:
    """atexit + SIGTERM se il runtime lo consente."""

    def _shutdown(*_args: object) -> None:
        guard.release()
        sys.exit(0)

    atexit.register(guard.release)
    sigterm = getattr(signal, "SIGTERM", None)
    if sigterm is None:
        return
    try:
        signal.signal(sigterm, _shutdown)
    except (ValueError, OSError):
        pass
