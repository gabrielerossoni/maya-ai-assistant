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
