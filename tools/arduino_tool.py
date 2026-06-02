from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import time
from typing import Callable, Optional

try:
    import serial
    import serial.tools.list_ports

    SERIAL_AVAILABLE = True
except ImportError:
    serial = None
    SERIAL_AVAILABLE = False

SERIAL_EXCEPTION = serial.SerialException if SERIAL_AVAILABLE else OSError

BAUD_RATE = 115200
TIMEOUT_SEC = 3
SERIAL_PORT = os.getenv("ARDUINO_PORT", "AUTO")
ARDUINO_BATCH_STEP_TIMEOUT = float(os.getenv("ARDUINO_BATCH_STEP_TIMEOUT", "1.0"))

VALID_TARGETS = {
    "light",
    "servo",
    "servo2",
    "rgb",
    "rgb1",
    "rgb2",
    "rgb3",
    "neopixel",
    "brightness",
    "buzzer",
    "buzzer2",
    "speaker",
    "sensor_read",
    "status",
}


class ArduinoTool:
    def __init__(self):
        self.connection = None
        self.simulated = not SERIAL_AVAILABLE
        self.sim_state = {
            "light": False,
            "servo": 0,
            "servo2": 0,
            "rgb1": [0, 0, 0],
            "rgb2": [0, 0, 0],
            "rgb3": [0, 0, 0],
            "neo_effect": 0,
            "brightness": 255,
            "buzzer": False,
            "buzz2_playing": False,
        }
        self._reader = None
        self._running = False
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._event_queue: queue.Queue = queue.Queue()
        self._telemetry: dict = {}
        self._event_hooks: list[Callable] = []
        self._sync_pending: dict[int, tuple[threading.Event, list]] = {}
        self._lock = threading.Lock()
        self._serial_lock = threading.Lock()

    def initialize(self):
        if not SERIAL_AVAILABLE:
            self.simulated = True
            print("[ARDUINO] pyserial assente → simulazione")
            return

        self._running = True
        self.simulated = True  # Inizia in modalità simulata finché non si connette

        # Prova una connessione iniziale veloce
        port = self._find_port() if SERIAL_PORT == "AUTO" else SERIAL_PORT
        if port:
            try:
                self.connection = serial.Serial(port, BAUD_RATE, timeout=0.1)
                time.sleep(2)
                self.simulated = False
                print(f"[ARDUINO] Connesso su {port} @ {BAUD_RATE}")
            except SERIAL_EXCEPTION as e:
                print(f"[ARDUINO] Connessione iniziale fallita su {port}: {e}")
        else:
            print("[ARDUINO] Porta non trovata all'avvio, monitoraggio in background attivo.")

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

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
                if not line or set(line) == {"."}:  # Ignora linee vuote o solo puntini (WiFi waiting)
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    # Log non-JSON lines for debugging if they aren't empty
                    if line:
                        print(f"[ARDUINO DEBUG] {line}")
                    continue

                self._dispatch(data)

            except SERIAL_EXCEPTION:
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

            with self._lock:
                sync_entry = self._sync_pending.pop(msg_id, None)
            if sync_entry:
                event, holder = sync_entry
                holder[0] = data
                event.set()

            if "state" in data:
                s = data["state"]
                self.sim_state.update(
                    {
                        "light": s.get("light", self.sim_state["light"]),
                        "servo": s.get("servo", self.sim_state["servo"]),
                        "servo2": s.get("servo2", self.sim_state.get("servo2", 0)),
                        "rgb1": s.get("rgb1", self.sim_state.get("rgb1", [0, 0, 0])),
                        "rgb2": s.get("rgb2", self.sim_state.get("rgb2", [0, 0, 0])),
                        "rgb3": s.get("rgb3", self.sim_state.get("rgb3", [0, 0, 0])),
                        "neo_effect": s.get("neo_effect", self.sim_state.get("neo_effect", 0)),
                        "brightness": s.get("brightness", self.sim_state.get("brightness", 255)),
                        "buzzer": s.get("buzzer", self.sim_state["buzzer"]),
                        "buzz2_playing": s.get("buzz2_playing", self.sim_state.get("buzz2_playing", False)),
                    }
                )

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
        cmd = action.get("command", "").upper()
        target = action.get("target", "")
        value = action.get("value", None)
        op = action.get("op", "SET")
        extra = {k: action[k] for k in ("effect", "melody") if k in action}

        # Auto-reconnection logic for simulated state
        if self.simulated and SERIAL_AVAILABLE:
            _now = time.time()
            if not hasattr(self, "_last_reconnect_attempt") or _now - self._last_reconnect_attempt > 8.0:
                self._last_reconnect_attempt = _now
                if self._reconnect():
                    print("[ARDUINO] Connessione fisica ripristinata con successo!")
        if str(op).upper() == "BATCH":
            return self._execute_batch(action.get("actions", []))

        # Alias: speaker → buzzer2 (stesso pin, protocollo invariato)
        if target == "speaker":
            target = "buzzer2"

        legacy_map = {
            "LIGHT_ON": ("SET", "light", 1),
            "LIGHT_OFF": ("SET", "light", 0),
            "SERVO_OPEN": ("SET", "servo", 90),
            "SERVO_CLOSE": ("SET", "servo", 0),
            "STATUS": ("GET", "status", None),
        }
        if cmd in legacy_map:
            op, target, value = legacy_map[cmd]

        op = str(op).upper()
        if target not in VALID_TARGETS:
            return {"status": "error", "message": f"target Arduino non supportato: {target}"}
        if op not in {"SET", "GET"}:
            return {"status": "error", "message": f"operazione Arduino non supportata: {op}"}

        if self.simulated:
            return self._simulate(op, target, value, **extra)

        if "timeout" in action:
            extra["timeout"] = float(action["timeout"])
        return self._send_sync(op, target, value, **extra)

    def _execute_batch(self, actions: list) -> dict:
        if not isinstance(actions, list) or not actions:
            return {"status": "error", "message": "batch Arduino vuoto"}
        invalid = self._validate_batch_actions(actions)
        if invalid:
            return {"status": "error", "message": invalid}

        if self.simulated:
            return self._simulate("BATCH", "batch", actions)

        batch_result = self._send_batch_sync(actions, timeout=max(1.5, ARDUINO_BATCH_STEP_TIMEOUT * len(actions)))
        if batch_result.get("status") == "ok":
            return batch_result

        if batch_result.get("message") not in {"bad_cmd", "timeout"}:
            return batch_result

        results = []
        errors = []
        for item in actions:
            if not isinstance(item, dict):
                return {"status": "error", "message": "azione batch Arduino non valida", "results": results}

            sub_action = {"tool": "arduino", "timeout": ARDUINO_BATCH_STEP_TIMEOUT, **item}
            result = self.execute(sub_action)
            results.append(result)
            if result.get("status") == "error":
                errors.append({"action": item, "message": result.get("message", "errore Arduino")})

        if errors and len(errors) == len(actions) and not all(e["message"] == "timeout" for e in errors):
            return {
                "status": "error",
                "message": errors[0]["message"],
                "errors": errors,
                "results": results,
                "state": self.sim_state.copy(),
            }
        if errors:
            return {"status": "partial", "errors": errors, "results": results, "state": self.sim_state.copy()}
        return {"status": "ok", "results": results, "state": self.sim_state.copy()}

    def _validate_batch_actions(self, actions: list) -> str:
        for item in actions:
            if not isinstance(item, dict):
                return "azione batch Arduino non valida"
            target = item.get("target", "")
            op = str(item.get("op", "SET")).upper()
            if target == "speaker":
                target = "buzzer2"
            if target not in VALID_TARGETS:
                return f"target Arduino non supportato: {target}"
            if op not in {"SET", "GET"}:
                return f"operazione Arduino non supportata: {op}"
        return ""

    def get_telemetry(self) -> dict:
        return self._telemetry.copy()

    def _next_id(self) -> int:
        with self._lock:
            self._msg_id += 1
            return self._msg_id

    def _send_sync(self, op: str, target: str, value, timeout=2.5, **extra) -> dict:
        msg_id = self._next_id()
        payload = {"id": msg_id, "cmd": op, "target": target}
        if value is not None:
            payload["value"] = value
        payload.update(extra)

        max_attempts = 2
        for attempt in range(max_attempts):
            event = threading.Event()
            holder: list = [None]
            with self._lock:
                self._sync_pending[msg_id] = (event, holder)

            try:
                with self._serial_lock:
                    if self.connection is None:
                        with self._lock:
                            self._sync_pending.pop(msg_id, None)
                        if not self._reconnect():
                            return {
                                "status": "error",
                                "message": "Arduino not connected",
                                "state": self.sim_state.copy(),
                            }

                    self.connection.write((json.dumps(payload) + "\n").encode())
                    self.connection.flush()
            except SERIAL_EXCEPTION:
                with self._lock:
                    self._sync_pending.pop(msg_id, None)
                self._reconnect()
                continue

            if event.wait(timeout=timeout):
                data = holder[0] or {}
                state = data.get("state", {})
                if state:
                    self.sim_state.update(
                        {
                            "light": state.get("light", self.sim_state["light"]),
                            "servo": state.get("servo", self.sim_state["servo"]),
                            "servo2": state.get("servo2", self.sim_state.get("servo2", 0)),
                            "rgb1": state.get("rgb1", self.sim_state.get("rgb1", [0, 0, 0])),
                            "rgb2": state.get("rgb2", self.sim_state.get("rgb2", [0, 0, 0])),
                            "rgb3": state.get("rgb3", self.sim_state.get("rgb3", [0, 0, 0])),
                            "neo_effect": state.get("neo_effect", self.sim_state.get("neo_effect", 0)),
                            "brightness": state.get("brightness", self.sim_state.get("brightness", 255)),
                            "buzzer": state.get("buzzer", self.sim_state["buzzer"]),
                            "buzz2_playing": state.get("buzz2_playing", self.sim_state.get("buzz2_playing", False)),
                        }
                    )
                status = data.get("status", "error")
                result = {"status": status, "state": self.sim_state.copy()}
                # Pass-through sensor data when present
                if "temp" in data:
                    result["temp"] = data.get("temp")
                if "humidity" in data:
                    result["humidity"] = data.get("humidity")
                if status == "error":
                    result["message"] = data.get("message") or data.get("msg") or "errore Arduino"
                return result
            else:
                with self._lock:
                    self._sync_pending.pop(msg_id, None)
                if attempt < max_attempts - 1:
                    time.sleep(0.1)
                    continue
                return {"status": "error", "message": "timeout", "state": self.sim_state.copy()}

        return {"status": "error", "message": "failed after retries", "state": self.sim_state.copy()}

    def _send_batch_sync(self, actions: list, timeout=4.0) -> dict:
        msg_id = self._next_id()
        payload_actions = []
        for item in actions:
            cmd = str(item.get("op", "SET")).upper()
            target = item["target"]
            if target == "speaker":
                target = "buzzer2"
            payload = {"cmd": cmd, "target": target}
            if "value" in item:
                payload["value"] = item["value"]
            for key in ("effect", "melody"):
                if key in item:
                    payload[key] = item[key]
            payload_actions.append(payload)

        payload = {"id": msg_id, "cmd": "BATCH", "actions": payload_actions}

        max_attempts = 2
        for attempt in range(max_attempts):
            event = threading.Event()
            holder: list = [None]
            with self._lock:
                self._sync_pending[msg_id] = (event, holder)

            try:
                with self._serial_lock:
                    if self.connection is None:
                        with self._lock:
                            self._sync_pending.pop(msg_id, None)
                        if not self._reconnect():
                            return {
                                "status": "error",
                                "message": "Arduino not connected",
                                "state": self.sim_state.copy(),
                            }

                    self.connection.write((json.dumps(payload) + "\n").encode())
                    self.connection.flush()
            except SERIAL_EXCEPTION:
                with self._lock:
                    self._sync_pending.pop(msg_id, None)
                self._reconnect()
                continue

            if event.wait(timeout=timeout):
                data = holder[0] or {}
                state = data.get("state", {})
                if state:
                    self.sim_state.update(
                        {
                            "light": state.get("light", self.sim_state["light"]),
                            "servo": state.get("servo", self.sim_state["servo"]),
                            "servo2": state.get("servo2", self.sim_state.get("servo2", 0)),
                            "rgb1": state.get("rgb1", self.sim_state.get("rgb1", [0, 0, 0])),
                            "rgb2": state.get("rgb2", self.sim_state.get("rgb2", [0, 0, 0])),
                            "rgb3": state.get("rgb3", self.sim_state.get("rgb3", [0, 0, 0])),
                            "neo_effect": state.get("neo_effect", self.sim_state.get("neo_effect", 0)),
                            "buzzer": state.get("buzzer", self.sim_state["buzzer"]),
                            "buzz2_playing": state.get("buzz2_playing", self.sim_state.get("buzz2_playing", False)),
                        }
                    )
                status = data.get("status", "error")
                result = {"status": status, "state": self.sim_state.copy()}
                if status == "error":
                    result["message"] = data.get("message") or data.get("msg") or "errore Arduino"
                return result

            with self._lock:
                self._sync_pending.pop(msg_id, None)
            if attempt < max_attempts - 1:
                time.sleep(0.2)
                continue
            return {"status": "error", "message": "timeout", "state": self.sim_state.copy()}

        return {"status": "error", "message": "failed after retries", "state": self.sim_state.copy()}

    def _simulate(self, op: str, target: str, value, **extra) -> dict:
        # Minimal, coherent simulation for offline/dev usage
        try:
            if op == "BATCH":
                results = []
                errors = []
                for item in value or []:
                    sub_op = str(item.get("op", "SET")).upper()
                    sub_target = item.get("target", "")
                    sub_value = item.get("value", None)
                    sub_extra = {k: item[k] for k in ("effect", "melody") if k in item}
                    if sub_target == "speaker":
                        sub_target = "buzzer2"
                    result = self._simulate(sub_op, sub_target, sub_value, **sub_extra)
                    results.append(result)
                    if result.get("status") == "error":
                        errors.append({"action": item, "message": result.get("message", "errore Arduino")})
                if errors:
                    return {"status": "partial", "errors": errors, "results": results, "state": self.sim_state.copy()}
                return {"status": "ok", "results": results, "state": self.sim_state.copy()}

            if op == "GET" and target == "status":
                return {"status": "ok", "state": self.sim_state.copy()}
            if op == "SET":
                if target == "light":
                    self.sim_state["light"] = bool(value)
                elif target == "servo":
                    self.sim_state["servo"] = int(value or 0)
                elif target == "servo2":
                    self.sim_state["servo2"] = int(value or 0)
                elif target in ("rgb", "neopixel"):
                    r = g = b = 0
                    if isinstance(value, dict):
                        r = int(value.get("r", 0))
                        g = int(value.get("g", 0))
                        b = int(value.get("b", 0))
                    elif isinstance(value, int):
                        r = (value >> 16) & 0xFF
                        g = (value >> 8) & 0xFF
                        b = value & 0xFF
                    self.sim_state["rgb1"] = [r, g, b]
                    self.sim_state["rgb2"] = [r, g, b]
                    self.sim_state["rgb3"] = [r, g, b]
                    self.sim_state["neo_effect"] = int(extra.get("effect", self.sim_state.get("neo_effect", 0)))
                elif target in ("rgb1", "rgb2", "rgb3"):
                    r = g = b = 0
                    if isinstance(value, dict):
                        r = int(value.get("r", 0))
                        g = int(value.get("g", 0))
                        b = int(value.get("b", 0))
                    elif isinstance(value, int):
                        r = (value >> 16) & 0xFF
                        g = (value >> 8) & 0xFF
                        b = value & 0xFF
                    self.sim_state[target] = [r, g, b]
                    self.sim_state["neo_effect"] = int(extra.get("effect", self.sim_state.get("neo_effect", 0)))
                elif target == "brightness":
                    v = 0 if value is None else int(value)
                    if v < 0:
                        v = 0
                    if v > 255:
                        v = 255
                    self.sim_state["brightness"] = v
                elif target == "buzzer":
                    self.sim_state["buzzer"] = bool(value)
                elif target == "buzzer2":
                    mel = str(extra.get("melody", "")).lower()
                    self.sim_state["buzz2_playing"] = False if mel in ("off", "stop") else True
                return {"status": "ok", "state": self.sim_state.copy()}
        except Exception:
            pass
        return {"status": "error", "message": "arduino non connesso"}

    def get_sensor_data(self) -> dict:
        if self.simulated or self.connection is None or not getattr(self.connection, "is_open", False):
            return None

        msg_id = self._next_id()
        payload = {"id": msg_id, "cmd": "GET", "target": "sensor_read"}

        event = threading.Event()
        holder: list = [None]
        with self._lock:
            self._sync_pending[msg_id] = (event, holder)

        try:
            with self._serial_lock:
                if self.connection is None:
                    with self._lock:
                        self._sync_pending.pop(msg_id, None)
                    return None
                self.connection.write((json.dumps(payload) + "\n").encode())
                self.connection.flush()
        except Exception:
            with self._lock:
                self._sync_pending.pop(msg_id, None)
            return None

        if event.wait(timeout=1.5):
            data = holder[0] or {}
            temp = data.get("temp")
            hum = data.get("humidity")
            res = {}
            if temp is not None:
                res["temp"] = float(temp)
            if hum is not None:
                res["humidity"] = float(hum)
            return res
        else:
            with self._lock:
                self._sync_pending.pop(msg_id, None)

        return None

    def _find_port(self) -> Optional[str]:
        if not SERIAL_AVAILABLE:
            return None
        for p in serial.tools.list_ports.comports():
            desc = (p.description or "").lower()
            if any(k in desc for k in ["arduino", "ch340", "atmega", "usb serial", "cp210", "seriale usb", "serial", "usb", "r4"]):
                return p.device
        return None

    def _reconnect(self):
        self.simulated = True
        self._telemetry = {}
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
        except SERIAL_EXCEPTION:
            return False

    def close(self):
        self._running = False
        if self.connection and self.connection.is_open:
            self.connection.close()
