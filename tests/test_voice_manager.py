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


def test_recover_audio_input_reopens_microphone_stream(monkeypatch):
    vm = _bare_voice_manager()
    vm.FORMAT = 8
    vm.CHANNELS = 1
    vm.RATE = 16000
    vm.CHUNK = 1280
    statuses = []
    calibrated = []
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
    monkeypatch.setattr("core.voice_manager.time.sleep", lambda _seconds: None)

    audio, stream = vm._recover_audio_input(old_audio, old_stream, OSError(-9999, "Unanticipated host error"))

    assert old_stream.stopped is True
    assert old_stream.closed is True
    assert old_audio.terminated is True
    assert audio is new_audio
    assert stream is new_stream
    assert statuses == ["IDLE"]
    assert calibrated == [new_stream]
