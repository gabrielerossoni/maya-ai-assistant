"""
tools/network_tool.py
Comunica con il secondo PC via socket TCP.
Invia comandi in formato JSON e riceve risposta.
"""

import socket
import json
import os

# ──────────────────────────────────────────────
# CONFIGURAZIONE
# ──────────────────────────────────────────────
REMOTE_HOST = os.getenv("REMOTE_HOST", "192.168.1.100")
REMOTE_PORT = int(os.getenv("REMOTE_PORT", 9999))
TIMEOUT_SEC = 5


class NetworkTool:
    """Tool per comunicazione TCP con il secondo PC."""

    def initialize(self):
        print(f"[NETWORK] Target: {REMOTE_HOST}:{REMOTE_PORT}")

    def execute(self, action: dict) -> dict:
        """
        Invia un messaggio al secondo PC.
        action: {"tool": "network", "message": "OPEN_APP:spotify"}
        """
        message = action.get("message", "PING")

        payload = json.dumps({
            "command": message,
            "source": "jarvis"
        })

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(TIMEOUT_SEC)
                s.connect((REMOTE_HOST, REMOTE_PORT))
                s.sendall(payload.encode("utf-8"))

                # Attendi risposta
                response_raw = s.recv(1024).decode("utf-8")
                response = json.loads(response_raw)

                print(f"[NETWORK] Risposta PC remoto: {response}")
                return {"status": "ok", "response": response}

        except ConnectionRefusedError:
            return {"status": "error", "message": "Secondo PC non raggiungibile"}
        except socket.timeout:
            return {"status": "error", "message": "Timeout connessione"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


# ══════════════════════════════════════════════
# SERVER (da eseguire sul SECONDO PC)
# python -c "from tools.network_tool import run_server; run_server()"
# ══════════════════════════════════════════════

def run_server(host="0.0.0.0", port=9999):
    """
    Server TCP da avviare sul secondo PC.
    Riceve comandi da Jarvis ed esegue azioni locali.
    """
    import subprocess

    COMMAND_HANDLERS = {
        "GOODNIGHT":   lambda: print("[SERVER] Buonanotte ricevuto!"),
        "WORK_MODE":   lambda: print("[SERVER] Modalità lavoro attivata!"),
        "OPEN_APP:spotify": lambda: subprocess.Popen(["spotify"]),
        "PING":        lambda: print("[SERVER] PONG"),
    }

    print(f"[SERVER] In ascolto su {host}:{port}...")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(5)

        while True:
            conn, addr = server.accept()
            print(f"[SERVER] Connessione da {addr}")

            with conn:
                data = conn.recv(4096).decode("utf-8")
                try:
                    payload = json.loads(data)
                    cmd = payload.get("command", "")
                    print(f"[SERVER] Comando: {cmd}")

                    # Esegui handler se esiste
                    handler = COMMAND_HANDLERS.get(cmd)
                    if handler:
                        handler()
                        resp = {"status": "ok", "executed": cmd}
                    else:
                        print(f"[SERVER] Comando sconosciuto: {cmd}")
                        resp = {"status": "unknown", "command": cmd}

                except json.JSONDecodeError:
                    resp = {"status": "error", "message": "JSON non valido"}

                conn.sendall(json.dumps(resp).encode("utf-8"))


if __name__ == "__main__":
    run_server()
