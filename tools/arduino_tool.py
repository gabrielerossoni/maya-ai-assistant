import threading
import queue
import time
import json
import os
import asyncio
from typing import Callable, Optional

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False

BAUD_RATE   = 115200
TIMEOUT_SEC = 3
SERIAL_PORT = os.getenv("ARDUINO_PORT", "AUTO")

VALID_TARGETS = {"light", "relay", "servo", "light_pwm"}

class ArduinoTool:
    def __init__(self):
        self.connection  = None
        self.simulated   = not SERIAL_AVAILABLE
        self.sim_state   = {"light": False, "relay": False, "servo": 0}
        self._reader     = None
        self._running    = False
        self._msg_id     = 0
        self._pending    : dict[int, asyncio.Future] = {}
        self._event_queue: queue.Queue = queue.Queue()
        self._telemetry  : dict = {}
        self._event_hooks: list[Callable] = []
        self._lock       = threading.Lock()

    def initialize(self):
        if not SERIAL_AVAILABLE:
            self.simulated = True
            print("[ARDUINO] pyserial assente → simulazione")
            return

        port = self._find_port() if SERIAL_PORT == "AUTO" else SERIAL_PORT
        if not port:
            self.simulated = True
            print("[ARDUINO] Porta non trovata → simulazione")
            return

        try:
            self.connection = serial.Serial(port, BAUD_RATE, timeout=0.1)
            time.sleep(2)
            self.simulated = False
            self._running  = True
            self._reader   = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()
            print(f"[ARDUINO] Connesso su {port} @ {BAUD_RATE}")
        except serial.SerialException as e:
            self.simulated = True
            print(f"[ARDUINO] Errore porta: {e} → simulazione")

    def register_event_hook(self, cb: Callable):
        self._event_hooks.append(cb)

    def _read_loop(self):
        while self._running:
            try:
                if not self.connection or not self.connection.is_open:
                    if not self._reconnect():
                        time.sleep(5)
                    continue

                line = self.connection.readline().decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    # Log non-JSON lines for debugging if they aren't empty
                    if line:
                        print(f"[ARDUINO DEBUG] {line}")
                    continue

                self._dispatch(data)

            except serial.SerialException:
                print("[ARDUINO] Connessione persa → tentativo riconnessione...")
                self._reconnect()
            except Exception as e:
                print(f"[ARDUINO] Reader error: {e}")
                time.sleep(1)

    def _dispatch(self, data: dict):
        if "id" in data and "status" in data:
            msg_id = data["id"]
            with self._lock:
                future = self._pending.pop(msg_id, None)
            if future and not future.done():
                try:
                    # Fix deprecated get_event_loop()
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        # Fallback if no loop is running in this thread
                        return
                    loop.call_soon_threadsafe(future.set_result, data)
                except Exception:
                    pass

            if "state" in data:
                s = data["state"]
                self.sim_state.update({
                    "light": s.get("light", self.sim_state["light"]),
                    "relay": s.get("relay", self.sim_state["relay"]),
                    "servo": s.get("servo", self.sim_state["servo"]),
                })

        elif "telemetry" in data:
            self._telemetry = data["telemetry"]
            self._fire_hooks({"type": "telemetry", **data["telemetry"]})

        elif "event" in data:
            self._event_queue.put(data)
            self._fire_hooks({"type": "event", **data})

    def _fire_hooks(self, payload: dict):
        for cb in self._event_hooks:
            try:
                cb(payload)
            except Exception:
                pass

    def execute(self, action: dict) -> dict:
        cmd    = action.get("command", "").upper()
        target = action.get("target", "")
        value  = action.get("value", None)
        op     = action.get("op", "SET")

        legacy_map = {
            "LIGHT_ON":    ("SET", "light",  1),
            "LIGHT_OFF":   ("SET", "light",  0),
            "RELAY_ON":    ("SET", "relay",  1),
            "RELAY_OFF":   ("SET", "relay",  0),
            "SERVO_OPEN":  ("SET", "servo",  90),
            "SERVO_CLOSE": ("SET", "servo",  0),
            "STATUS":      ("GET", "status", None),
        }
        if cmd in legacy_map:
            op, target, value = legacy_map[cmd]

        if self.simulated:
            return self._simulate(op, target, value)

        return self._send_sync(op, target, value)

    def get_telemetry(self) -> dict:
        return self._telemetry.copy()

    def _next_id(self) -> int:
        with self._lock:
            self._msg_id += 1
            return self._msg_id

    def _send_sync(self, op: str, target: str, value, timeout=1.0) -> dict:
        msg_id  = self._next_id()
        payload = {"id": msg_id, "cmd": op, "target": target}
        if value is not None:
            payload["value"] = value

        # Cleanup expired futures to prevent memory leaks
        with self._lock:
            expired = [mid for mid, fut in self._pending.items() if fut.done()]
            for mid in expired:
                self._pending.pop(mid)

        try:
            self.connection.write((json.dumps(payload) + "\n").encode())
            self.connection.flush()
        except serial.SerialException as e:
            return {"status": "error", "message": str(e)}

        time.sleep(0.2)
        return {
            "status": "ok",
            "state": self.sim_state.copy(),
            "note": "command_sent"
        }

    def _simulate(self, op: str, target: str, value) -> dict:
        if op == "SET":
            if target == "light":
                self.sim_state["light"] = bool(value)
            elif target == "relay":
                self.sim_state["relay"] = bool(value)
            elif target == "servo":
                self.sim_state["servo"] = max(0, min(180, int(value)))
            print(f"[ARDUINO SIM] {target} → {value}")

        return {"status": "ok", "simulated": True, "state": self.sim_state.copy()}

    def _find_port(self) -> Optional[str]:
        for p in serial.tools.list_ports.comports():
            desc = (p.description or "").lower()
            if any(k in desc for k in ["arduino", "ch340", "atmega", "usb serial", "cp210"]):
                return p.device
        return None

    def _reconnect(self):
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
        self.connection = None
        
        # Try to reconnect without spawning a new thread
        port = self._find_port() if SERIAL_PORT == "AUTO" else SERIAL_PORT
        if not port:
            return False
            
        try:
            self.connection = serial.Serial(port, BAUD_RATE, timeout=0.1)
            time.sleep(2)
            self.simulated = False
            print(f"[ARDUINO] Riconnesso su {port} @ {BAUD_RATE}")
            return True
        except serial.SerialException:
            return False

    def close(self):
        self._running = False
        if self.connection and self.connection.is_open:
            self.connection.close()
