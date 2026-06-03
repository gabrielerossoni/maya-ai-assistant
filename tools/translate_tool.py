"""
translate_tool.py - Traduzione testo
"""

from deep_translator import GoogleTranslator


class TranslateTool:
    def initialize(self):
        pass

    def execute(self, action: dict) -> dict:
        parametro = action.get("parametro")

        text = action.get("text") or action.get("query") or action.get("input") or action.get("value")

        if not text and isinstance(parametro, str):
            text = parametro

        if not text and isinstance(parametro, dict):
            text = parametro.get("text") or parametro.get("query") or parametro.get("input") or parametro.get("value")

        target_lang = (
            action.get("target") or action.get("target_lang") or action.get("language") or action.get("lang") or "en"
        )

        if isinstance(parametro, dict):
            target_lang = (
                parametro.get("target")
                or parametro.get("target_lang")
                or parametro.get("language")
                or parametro.get("lang")
                or target_lang
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
