"""
translate_tool.py - Traduzione testo
"""
from deep_translator import GoogleTranslator

class TranslateTool:
    def initialize(self):
        pass

    def execute(self, action: dict) -> dict:
        text = action.get("text", "")
        target_lang = action.get("target", "en") # codice lingua, es. 'en', 'es', 'ja'
        
        if not text:
            return {"status": "error", "message": "Nessun testo da tradurre."}

        try:
            translated = GoogleTranslator(source='auto', target=target_lang).translate(text)
            return {"status": "ok", "message": f"Traduzione ({target_lang}): {translated}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
