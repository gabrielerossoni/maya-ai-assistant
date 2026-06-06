import concurrent.futures
import sys
from types import SimpleNamespace

sys.modules.setdefault("pyaudio", SimpleNamespace(paInt16=8, PyAudio=lambda: None))
sys.modules.setdefault("faster_whisper", SimpleNamespace(WhisperModel=object))

from core.voice_manager import VoiceManager


def _bare_voice_manager():
    vm = VoiceManager.__new__(VoiceManager)
    vm.piper_exe = "voice/piper.exe"
    vm.piper_model = "voice/model.onnx"
    vm.is_speaking = False
    vm._audio_recovery_attempts = 0
    vm._max_audio_recovery_attempts = 5
    return vm


def test_speak_returns_dashboard_to_idle(monkeypatch):
    vm = _bare_voice_manager()
    statuses = []
    vm._broadcast = statuses.append
    vm._play_wav = lambda _: None
    monkeypatch.setattr("core.voice_manager.os.path.exists", lambda _: True)
    monkeypatch.setattr("core.voice_manager.os.makedirs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("core.voice_manager.subprocess.run", lambda *_args, **_kwargs: None)

    vm.speak("ciao")

    assert statuses == ["SPEAKING", "IDLE"]
    assert vm.is_speaking is False


def test_speak_returns_dashboard_to_idle_on_playback_error(monkeypatch):
    vm = _bare_voice_manager()
    statuses = []
    vm._broadcast = statuses.append

    def fail_playback(_):
        raise RuntimeError("audio failed")

    vm._play_wav = fail_playback
    monkeypatch.setattr("core.voice_manager.os.path.exists", lambda _: True)
    monkeypatch.setattr("core.voice_manager.os.makedirs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("core.voice_manager.subprocess.run", lambda *_args, **_kwargs: None)

    vm.speak("ciao")

    assert statuses == ["SPEAKING", "IDLE"]
    assert vm.is_speaking is False


def test_speak_raw_returns_dashboard_to_idle_when_standalone(monkeypatch):
    vm = _bare_voice_manager()
    statuses = []
    vm._broadcast = statuses.append
    vm._play_wav = lambda _: None
    monkeypatch.setattr("core.voice_manager.os.path.exists", lambda _: True)
    monkeypatch.setattr("core.voice_manager.os.makedirs", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("core.voice_manager.subprocess.run", lambda *_args, **_kwargs: None)

    vm._speak_raw("ciao")

    assert statuses == ["SPEAKING", "IDLE"]


def test_speak_raw_splits_long_text_before_piper(monkeypatch):
    vm = _bare_voice_manager()
    vm._broadcast = lambda _status: None
    vm._play_wav = lambda _: None
    calls = []
    monkeypatch.setattr("core.voice_manager.os.path.exists", lambda _: True)
    monkeypatch.setattr("core.voice_manager.os.makedirs", lambda *_args, **_kwargs: None)

    def fake_run(_command, input, **_kwargs):
        calls.append(input.decode("utf-8"))

    monkeypatch.setattr("core.voice_manager.subprocess.run", fake_run)

    vm._speak_raw("Questa e' una frase molto lunga. " * 20)

    assert len(calls) > 1
    assert all(len(call) <= 260 for call in calls)


def test_start_resets_audio_recovery_attempts(monkeypatch):
    vm = _bare_voice_manager()
    vm._audio_recovery_attempts = 4
    started = []
    monkeypatch.setattr(
        "core.voice_manager.threading.Thread",
        lambda target, daemon: SimpleNamespace(start=lambda: started.append((target, daemon))),
    )

    vm.start()

    assert vm._audio_recovery_attempts == 0
    assert vm.is_running is True
    assert started == [(vm._run_loop, True)]


def test_recover_audio_input_reopens_microphone_stream(monkeypatch):
    vm = _bare_voice_manager()
    vm.is_running = True
    vm.FORMAT = 8
    vm.CHANNELS = 1
    vm.RATE = 16000
    vm.CHUNK = 1280
    statuses = []
    calibrated = []
    sleeps = []
    vm._broadcast = statuses.append
    vm._calibrate_vad_from_stream = calibrated.append

    old_stream = SimpleNamespace(
        stopped=False,
        closed=False,
        stop_stream=lambda: setattr(old_stream, "stopped", True),
        close=lambda: setattr(old_stream, "closed", True),
    )
    old_audio = SimpleNamespace(terminated=False, terminate=lambda: setattr(old_audio, "terminated", True))
    new_stream = SimpleNamespace()
    new_audio = SimpleNamespace(open=lambda **_kwargs: new_stream, terminate=lambda: None)
    monkeypatch.setattr("core.voice_manager.pyaudio.PyAudio", lambda: new_audio)
    vm._sleep_while_running = lambda delay: sleeps.append(delay) or True

    audio, stream = vm._recover_audio_input(old_audio, old_stream, OSError(-9999, "Unanticipated host error"))

    assert old_stream.stopped is True
    assert old_stream.closed is True
    assert old_audio.terminated is True
    assert audio is new_audio
    assert stream is new_stream
    assert statuses == ["IDLE"]
    assert sleeps == [0.5]
    assert calibrated == [new_stream]


def test_broadcast_ignores_cancelled_future(monkeypatch, capsys):
    vm = _bare_voice_manager()
    vm._loop_ready = SimpleNamespace(is_set=lambda: True)
    vm.socket_manager = None
    vm.agent = SimpleNamespace(loop=object())

    class Future:
        def result(self):
            raise concurrent.futures.CancelledError()

        def add_done_callback(self, callback):
            callback(self)

    def fake_run_coroutine_threadsafe(coro, _loop):
        coro.close()
        return Future()

    monkeypatch.setattr("core.voice_manager.asyncio.run_coroutine_threadsafe", fake_run_coroutine_threadsafe)

    vm._broadcast("IDLE")

    assert capsys.readouterr().out == ""


def test_broadcast_skips_closed_loop(monkeypatch):
    vm = _bare_voice_manager()
    vm._loop_ready = SimpleNamespace(is_set=lambda: True)
    vm.socket_manager = None
    vm.agent = SimpleNamespace(loop=SimpleNamespace(is_closed=lambda: True))
    called = []
    monkeypatch.setattr("core.voice_manager.asyncio.run_coroutine_threadsafe", lambda *_args: called.append(True))

    vm._broadcast("IDLE")

    assert called == []


def test_recover_audio_input_closes_partial_reopen_on_calibration_failure(monkeypatch):
    vm = _bare_voice_manager()
    vm.is_running = True
    vm._max_audio_recovery_attempts = 2
    statuses = []
    sleeps = []
    vm._broadcast = statuses.append
    vm._sleep_while_running = lambda delay: sleeps.append(delay) or True

    new_stream = SimpleNamespace(
        stopped=False,
        closed=False,
        stop_stream=lambda: setattr(new_stream, "stopped", True),
        close=lambda: setattr(new_stream, "closed", True),
    )
    new_audio = SimpleNamespace(terminated=False, terminate=lambda: setattr(new_audio, "terminated", True))
    vm._open_audio_input = lambda: (new_audio, new_stream)
    vm._calibrate_vad_from_stream = lambda _stream: (_ for _ in ()).throw(OSError("calibration failed"))

    result = vm._recover_audio_input(None, None, OSError("read failed"))

    assert result is None
    assert new_stream.stopped is True
    assert new_stream.closed is True
    assert new_audio.terminated is True
    assert statuses == ["IDLE"]
    assert sleeps == [0.5]
    assert vm._audio_recovery_attempts == 1


def test_recover_audio_input_backs_off_after_reopen_failure():
    vm = _bare_voice_manager()
    vm.is_running = True
    statuses = []
    sleeps = []
    vm._broadcast = statuses.append
    vm._open_audio_input = lambda: (_ for _ in ()).throw(OSError("device locked"))
    vm._calibrate_vad_from_stream = lambda _stream: None

    old_stream = SimpleNamespace(stop_stream=lambda: None, close=lambda: None)
    old_audio = SimpleNamespace(terminate=lambda: None)
    vm._sleep_while_running = lambda delay: sleeps.append(delay) or True

    first = vm._recover_audio_input(old_audio, old_stream, OSError("read failed"))

    second = vm._recover_audio_input(None, None, OSError("read failed again"))

    assert first is None
    assert second is None
    assert statuses == ["IDLE", "IDLE"]
    assert sleeps == [0.5, 1.0]
    assert vm._audio_recovery_attempts == 2
    assert vm.is_running is True


def test_recover_audio_input_stops_after_max_failures():
    vm = _bare_voice_manager()
    vm.is_running = True
    vm._max_audio_recovery_attempts = 2
    statuses = []
    sleeps = []
    vm._broadcast = statuses.append
    vm._open_audio_input = lambda: (_ for _ in ()).throw(OSError("device missing"))
    vm._calibrate_vad_from_stream = lambda _stream: None
    vm._sleep_while_running = lambda delay: sleeps.append(delay) or True

    for _ in range(2):
        assert vm._recover_audio_input(None, None, OSError("read failed")) is None

    assert statuses == ["IDLE", "IDLE", "MIC_ERROR"]
    assert sleeps == [0.5, 1.0]
    assert vm._audio_recovery_attempts == 2
    assert vm.is_running is False


def test_recover_audio_input_aborts_backoff_when_stopped():
    vm = _bare_voice_manager()
    vm.is_running = False
    statuses = []
    opened = []
    vm._broadcast = statuses.append
    vm._open_audio_input = lambda: opened.append(True)

    result = vm._recover_audio_input(None, None, OSError("read failed"))

    assert result is None
    assert statuses == ["IDLE"]
    assert opened == []
