import json

import core.instance_guard as instance_guard


def test_instance_guard_writes_json_pid_metadata(tmp_path, monkeypatch):
    pid_file = tmp_path / "maya.pid"
    monkeypatch.setattr(instance_guard, "PID_FILE", str(pid_file))
    monkeypatch.setattr(instance_guard.os, "getpid", lambda: 1234)

    guard = instance_guard.InstanceGuard()
    guard._write_pid()
    guard.update_port(8012)

    data = json.loads(pid_file.read_text(encoding="ascii"))
    assert data["pid"] == 1234
    assert data["port"] == 8012
    assert isinstance(data["started_at"], float)


def test_read_pid_metadata_accepts_legacy_plain_pid(tmp_path, monkeypatch):
    pid_file = tmp_path / "maya.pid"
    pid_file.write_text("4321", encoding="ascii")
    monkeypatch.setattr(instance_guard, "PID_FILE", str(pid_file))

    assert instance_guard._read_pid_metadata() == {"pid": 4321, "port": None, "raw": "4321"}


def test_request_http_shutdown_uses_exact_port(monkeypatch):
    calls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _size):
            return b'{"status":"ok"}'

    def fake_urlopen(req, timeout):
        calls.append((req.full_url, timeout))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert instance_guard._request_http_shutdown(99, port=8123) is True
    assert calls == [("http://127.0.0.1:8123/shutdown?pid=99", 1.2)]


def test_request_http_shutdown_legacy_scans_when_port_unknown(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(req.full_url)
        raise OSError("closed")

    monkeypatch.setenv("MAYA_PORT", "9000")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert instance_guard._request_http_shutdown(99, port=None) is False
    assert calls[0] == "http://127.0.0.1:9000/shutdown?pid=99"
    assert calls[-1] == "http://127.0.0.1:9023/shutdown?pid=99"
    assert len(calls) == 24
