"""
Istanza unica: PID file + bind su porta locale dedicata (il socket evita stale lock dopo crash).
Bypass: MAYA_SKIP_INSTANCE_GUARD=1
"""

from __future__ import annotations

import atexit
import json
import os
import socket
import tempfile
import time


def pid_file_path() -> str:
    """Percorso cross-platform fuori dai binari del progetto."""
    root = (os.environ.get("MAYA_RUNTIME_DIR") or tempfile.gettempdir()).rstrip(os.sep)
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
        # SO_REUSEPORT=0 combinato garantisce lock anche su Linux
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            if hasattr(socket, "SO_REUSEPORT"):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 0)
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
        self._write_metadata({"pid": os.getpid(), "port": None, "started_at": time.time()})

    def update_port(self, port: int) -> None:
        self._write_metadata({"pid": os.getpid(), "port": int(port), "started_at": time.time()})

    def _write_metadata(self, metadata: dict) -> None:
        tmp = PID_FILE + ".tmp"
        with open(tmp, "w", encoding="ascii") as f:
            f.write(json.dumps(metadata, separators=(",", ":")))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, PID_FILE)


def _read_pid_metadata() -> dict:
    with open(PID_FILE, encoding="ascii") as f:
        raw = f.read().strip()
    if not raw:
        raise ValueError("PID file vuoto")
    if raw.startswith("{"):
        data = json.loads(raw)
        pid = int(data.get("pid", 0))
        if pid <= 0:
            raise ValueError("PID non positivo")
        port = data.get("port")
        return {"pid": pid, "port": int(port) if port is not None else None, "raw": raw}

    pid = int(raw)
    if pid <= 0:
        raise ValueError("PID non positivo")
    return {"pid": pid, "port": None, "raw": raw}


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

    try:
        metadata = _read_pid_metadata()
        pid = metadata["pid"]
        port = metadata.get("port")
    except (ValueError, json.JSONDecodeError, OSError) as e:
        try:
            with open(PID_FILE, encoding="ascii") as f:
                raw = f.read().strip()
        except OSError:
            raw = ""
        preview = raw if raw else "(vuoto)"
        print(f"[KILL] PID file non valido ({PID_FILE}): contenuto malformato ({preview!r}) - {e}. Rimuovo il file.")
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
    if _request_http_shutdown(pid, port=port):
        try:
            proc.wait(timeout=10)
            print("[KILL] Processo terminato con shutdown ordinato.")
            try:
                if os.path.isfile(PID_FILE):
                    os.remove(PID_FILE)
            except OSError:
                pass
            return True
        except psutil.TimeoutExpired:
            print("[KILL] Shutdown ordinato scaduto, passo alla terminazione processo.")

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


def _request_http_shutdown(pid: int, port: int | None = None) -> bool:
    import urllib.error
    import urllib.request

    first = int(os.environ.get("MAYA_PORT", "8000"))
    ports = [port] if port is not None else list(range(first, first + 24))
    for candidate_port in ports:
        url = f"http://127.0.0.1:{candidate_port}/shutdown?pid={pid}"
        req = urllib.request.Request(url, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=1.2) as res:
                body = res.read(256).decode("utf-8", errors="ignore").replace(" ", "")
                if res.status == 200 and '"status":"ok"' in body:
                    print(f"[KILL] Richiesto shutdown ordinato su porta {candidate_port}.")
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            continue
    return False


def skip_guard() -> bool:
    return os.environ.get("MAYA_SKIP_INSTANCE_GUARD", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def install_signal_handlers(guard: InstanceGuard) -> None:
    """Rilascia il lock a processo terminato senza intercettare i segnali uvicorn."""
    atexit.register(guard.release)
