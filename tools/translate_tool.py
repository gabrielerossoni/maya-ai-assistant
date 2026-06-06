"""
translate_tool.py - Traduzione testo
"""

from deep_translator import GoogleTranslator

from tools.param_utils import resolve_alias


class TranslateTool:
    def initialize(self):
        pass

    def execute(self, action: dict) -> dict:
        text = resolve_alias(action, ("text", "query", "input", "value"), allow_legacy_string=True)

        target_lang = resolve_alias(
            action,
            ("target", "target_lang", "language", "lang"),
            default="en",
        )

        if not text or not str(text).strip():
            return {"status": "error", "message": "Nessun testo da tradurre."}

        text = str(text).strip()
        target_lang = str(target_lang).strip().lower()

        try:
            translated = GoogleTranslator(source="auto", target=target_lang).translate(text)

            return {
                "status": "ok",
                "message": translated,
                "original": text,
                "target": target_lang,
            }

        except Exception as e:
            return {"status": "error", "message": f"Errore traduzione: {e}"}
