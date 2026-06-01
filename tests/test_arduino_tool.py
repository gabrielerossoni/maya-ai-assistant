import json

import pytest

from core.automation_engine import build_default_automations
from tools.arduino_tool import VALID_TARGETS, ArduinoTool


class ReplyingConnection:
    is_open = True

    def __init__(self, tool, response):
        self.tool = tool
        self.response = response
        self.writes = []
        self.flushed = False

    def write(self, raw):
        self.writes.append(raw)
        payload = json.loads(raw.decode().strip())
        response = self.response(payload) if callable(self.response) else self.response
        if response is not None:
            event, holder = self.tool._sync_pending[payload["id"]]
            holder[0] = {"id": payload["id"], **response}
            event.set()

    def flush(self):
        self.flushed = True


@pytest.fixture
def real_tool():
    tool = ArduinoTool()
    tool.simulated = False
    return tool


def test_all_default_scene_arduino_targets_are_supported():
    targets = {
        action.params.get("target")
        for automation in build_default_automations()
        for action in automation.scene.actions
        if action.tool == "arduino"
    }

    assert targets
    assert targets <= VALID_TARGETS


def test_execute_forwards_effect_and_melody(real_tool, monkeypatch):
    captured = []

    def fake_send(op, target, value, **extra):
        captured.append((op, target, value, extra))
        return {"status": "ok", "state": {}}

    monkeypatch.setattr(real_tool, "_send_sync", fake_send)

    real_tool.execute({"op": "SET", "target": "neopixel", "value": 0xFF0000, "effect": 3})
    real_tool.execute({"op": "SET", "target": "buzzer2", "melody": "alarm"})

    assert captured[0] == ("SET", "neopixel", 0xFF0000, {"effect": 3})
    assert captured[1] == ("SET", "buzzer2", None, {"melody": "alarm"})


def test_execute_accepts_every_declared_target(real_tool, monkeypatch):
    captured = []

    def fake_send(op, target, value, **extra):
        captured.append((op, target, value, extra))
        return {"status": "ok", "state": {}}

    monkeypatch.setattr(real_tool, "_send_sync", fake_send)

    for target in VALID_TARGETS:
        action = (
            {"op": "GET", "target": target}
            if target in {"sensor_read", "status"}
            else {
                "op": "SET",
                "target": target,
                "value": 1,
            }
        )
        assert real_tool.execute(action)["status"] == "ok"

    captured_targets = {entry[1] for entry in captured}
    assert captured_targets == (VALID_TARGETS - {"speaker"}) | {"buzzer2"}


def test_execute_maps_legacy_commands(real_tool, monkeypatch):
    captured = []
    monkeypatch.setattr(
        real_tool,
        "_send_sync",
        lambda op, target, value, **extra: captured.append((op, target, value)) or {"status": "ok"},
    )

    real_tool.execute({"command": "LIGHT_ON"})
    real_tool.execute({"command": "LIGHT_OFF"})
    real_tool.execute({"command": "SERVO_OPEN"})
    real_tool.execute({"command": "SERVO_CLOSE"})
    real_tool.execute({"command": "STATUS"})

    assert captured == [
        ("SET", "light", 1),
        ("SET", "light", 0),
        ("SET", "servo", 90),
        ("SET", "servo", 0),
        ("GET", "status", None),
    ]


def test_execute_normalizes_op_and_speaker_alias(real_tool, monkeypatch):
    captured = []
    monkeypatch.setattr(
        real_tool,
        "_send_sync",
        lambda op, target, value, **extra: captured.append((op, target, value, extra)) or {"status": "ok"},
    )

    result = real_tool.execute({"op": "set", "target": "speaker", "melody": "notify"})

    assert result["status"] == "ok"
    assert captured == [("SET", "buzzer2", None, {"melody": "notify"})]


def test_execute_rejects_unknown_target_and_bad_op(real_tool, monkeypatch):
    called = False

    def fake_send(*args, **kwargs):
        nonlocal called
        called = True
        return {"status": "ok"}

    monkeypatch.setattr(real_tool, "_send_sync", fake_send)

    bad_target = real_tool.execute({"op": "SET", "target": "../bad", "value": 1})
    bad_op = real_tool.execute({"op": "DELETE", "target": "light", "value": 1})

    assert bad_target["status"] == "error"
    assert "target Arduino" in bad_target["message"]
    assert bad_op["status"] == "error"
    assert "operazione Arduino" in bad_op["message"]
    assert called is False


def test_simulated_mode_updates_offline_state():
    tool = ArduinoTool()
    tool.simulated = True

    result = tool.execute({"op": "SET", "target": "light", "value": 1})

    assert result["status"] == "ok"
    assert result["state"]["light"] is True


def test_dispatch_updates_state_telemetry_and_event_hooks():
    tool = ArduinoTool()
    seen = []
    tool.register_event_hook(seen.append)

    tool._dispatch(
        {
            "id": 1,
            "status": "ok",
            "state": {
                "light": True,
                "servo": 90,
                "servo2": 45,
                "rgb1": [1, 2, 3],
                "rgb2": [4, 5, 6],
                "rgb3": [7, 8, 9],
                "neo_effect": 2,
                "buzzer": True,
                "buzz2_playing": True,
            },
        }
    )
    tool._dispatch({"telemetry": {"temp": 21.5, "humidity": 60}})
    tool._dispatch({"event": "button", "pin": 8})

    assert tool.sim_state["servo"] == 90
    assert tool.sim_state["rgb3"] == [7, 8, 9]
    assert tool.get_telemetry() == {"temp": 21.5, "humidity": 60}
    assert seen == [
        {"type": "telemetry", "temp": 21.5, "humidity": 60},
        {"type": "event", "event": "button", "pin": 8},
    ]


def test_send_sync_writes_json_payload_and_updates_state(real_tool):
    real_tool.connection = ReplyingConnection(
        real_tool,
        {
            "status": "ok",
            "state": {
                "light": True,
                "servo": 90,
                "rgb1": [255, 0, 0],
                "neo_effect": 3,
            },
        },
    )

    result = real_tool._send_sync("SET", "neopixel", 0xFF0000, effect=3)

    sent = json.loads(real_tool.connection.writes[0].decode().strip())
    assert sent["cmd"] == "SET"
    assert sent["target"] == "neopixel"
    assert sent["value"] == 0xFF0000
    assert sent["effect"] == 3
    assert real_tool.connection.flushed is True
    assert result["status"] == "ok"
    assert result["state"]["rgb1"] == [255, 0, 0]
    assert result["state"]["neo_effect"] == 3


def test_send_sync_preserves_arduino_error_status(real_tool):
    real_tool.connection = ReplyingConnection(real_tool, {"status": "error", "msg": "unknown_target"})

    result = real_tool._send_sync("SET", "light", 1)

    assert result["status"] == "error"
    assert result["message"] == "unknown_target"


def test_send_sync_timeout_and_missing_connection_cleanup(real_tool, monkeypatch):
    monkeypatch.setattr(real_tool, "_find_port", lambda: None)
    real_tool.connection = ReplyingConnection(real_tool, None)

    timeout = real_tool._send_sync("SET", "light", 1, timeout=0)
    assert timeout["status"] == "error"
    assert timeout["message"] == "timeout"
    assert real_tool._sync_pending == {}

    real_tool.connection = None
    missing = real_tool._send_sync("SET", "light", 1)
    assert missing["status"] == "error"
    assert missing["message"] == "Arduino not connected"
    assert real_tool._sync_pending == {}


def test_batch_continues_after_timeout(real_tool, monkeypatch):
    sent = []

    def fake_send(op, target, value, **extra):
        sent.append(target)
        if target == "light":
            return {"status": "error", "message": "timeout", "state": {}}
        return {"status": "ok", "state": {}}

    monkeypatch.setattr(
        real_tool,
        "_send_batch_sync",
        lambda actions, timeout=3.0: {"status": "error", "message": "timeout", "state": {}},
    )
    monkeypatch.setattr(real_tool, "_send_sync", fake_send)

    result = real_tool.execute(
        {
            "op": "BATCH",
            "actions": [
                {"op": "SET", "target": "light", "value": 1},
                {"op": "SET", "target": "rgb", "value": 0xFFD580},
                {"op": "SET", "target": "servo", "value": 0},
            ],
        }
    )

    assert result["status"] == "partial"
    assert sent == ["light", "rgb", "servo"]


def test_batch_treats_all_timeouts_as_partial(real_tool, monkeypatch):
    monkeypatch.setattr(
        real_tool,
        "_send_batch_sync",
        lambda actions, timeout=3.0: {"status": "error", "message": "timeout", "state": {}},
    )
    monkeypatch.setattr(
        real_tool,
        "_send_sync",
        lambda op, target, value, **extra: {"status": "error", "message": "timeout", "state": {}},
    )

    result = real_tool.execute(
        {
            "op": "BATCH",
            "actions": [
                {"op": "SET", "target": "light", "value": 1},
                {"op": "SET", "target": "rgb", "value": 0xFFD580},
            ],
        }
    )

    assert result["status"] == "partial"


def test_batch_prefers_single_serial_command(real_tool):
    real_tool.connection = ReplyingConnection(
        real_tool,
        {
            "status": "ok",
            "state": {
                "light": True,
                "servo": 0,
                "rgb1": [255, 213, 128],
            },
        },
    )

    result = real_tool.execute(
        {
            "op": "BATCH",
            "actions": [
                {"op": "SET", "target": "light", "value": 1},
                {"op": "SET", "target": "rgb", "value": 0xFFD580},
                {"op": "SET", "target": "servo", "value": 0},
            ],
        }
    )

    sent = json.loads(real_tool.connection.writes[0].decode().strip())
    assert sent["cmd"] == "BATCH"
    assert [a["target"] for a in sent["actions"]] == ["light", "rgb", "servo"]
    assert len(real_tool.connection.writes) == 1
    assert result["status"] == "ok"
    assert result["state"]["light"] is True


def test_get_sensor_data_sends_get_and_converts_numbers(real_tool):
    real_tool.connection = ReplyingConnection(real_tool, {"status": "ok", "temp": "22.5", "humidity": "61"})

    result = real_tool.get_sensor_data()

    sent = json.loads(real_tool.connection.writes[0].decode().strip())
    assert sent["cmd"] == "GET"
    assert sent["target"] == "sensor_read"
    assert result == {"temp": 22.5, "humidity": 61.0}


def test_get_sensor_data_returns_none_and_cleans_pending_without_connection(real_tool):
    real_tool.connection = None

    assert real_tool.get_sensor_data() is None
    assert real_tool._sync_pending == {}
