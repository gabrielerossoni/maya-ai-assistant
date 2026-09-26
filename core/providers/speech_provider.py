"""Thin voice capability adapter."""

class SpeechProvider:
    def __init__(self, voice_manager):
        self.voice_manager = voice_manager

    def health(self) -> bool:
        return self.voice_manager is not None

    def speak(self, text: str) -> None:
        self.voice_manager.speak(text)
