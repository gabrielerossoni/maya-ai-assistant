"""
self_healer.py - Auto-riparazione dei tool tramite LLM.
Intercetta errori ripetuti, genera patch via Groq, le salva in plugins/ per hot-reload.
La patch NON sovrascrive mai tools/ — usa il PluginLoader come vettore sicuro.
"""

import ast
import asyncio
import inspect
import os
import re

import httpx


class SelfHealer:
    """
    Intercetta errori ripetuti sui tool e tenta riparazione via LLM.
    La patch finisce in plugins/ (hot-reload automatico), NON sovrascrive tools/.
    """

    _HEAL_PROMPT = """Sei l'Ingegnere di Sistema di MAYA.
Analizza il fallimento e genera una versione corretta del tool.

VINCOLI CRITICI:
- Mantieni IDENTICA la firma della classe e del metodo execute().
- Il file deve essere self-contained (no import da tools/).
- Se l'errore è una API key mancante, aggiungi un check esplicito all'inizio di execute() che ritorna {"status": "error", "message": "API_KEY_MISSING: <nome_var>"}.
- Se l'errore è una libreria mancante, usa un try/import con fallback.
- Aggiungi un commento # SELF_HEALER_PATCH: <descrizione fix> all'inizio del file.

Rispondi SOLO con il codice Python completo. Zero testo fuori dal codice."""

    def __init__(self, tool_manager):
        self.tool_manager = tool_manager
        self._error_counts: dict[str, int] = {}
        self._patched: set[str] = set()
        self.ERROR_THRESHOLD = 3

    def record_success(self, tool_name: str):
        """Resetta il contatore errori su esecuzione ok."""
        self._error_counts.pop(tool_name, None)

    def record_error(self, tool_name: str, error: Exception, source_file: str):
        """Incrementa il contatore; dopo ERROR_THRESHOLD tenta il fix."""
        count = self._error_counts.get(tool_name, 0) + 1
        self._error_counts[tool_name] = count
        if count >= self.ERROR_THRESHOLD and tool_name not in self._patched:
            self._patched.add(tool_name)
            asyncio.create_task(self._attempt_fix(tool_name, error, source_file))

    async def _attempt_fix(self, tool_name: str, error: Exception, source_file: str):
        print(f"[SELF_HEALER] Tentativo fix per '{tool_name}' dopo {self.ERROR_THRESHOLD} errori consecutivi")

        if not source_file or not os.path.exists(source_file):
            print(f"[SELF_HEALER] File sorgente non trovato: {source_file}")
            return

        with open(source_file, "r", encoding="utf-8") as f:
            original_code = f.read()

        import traceback as _tb

        tb_text = _tb.format_exc()

        user_msg = (
            f"Tool: {tool_name}\n"
            f"File: {source_file}\n\n"
            f"TRACEBACK:\n{tb_text[-1500:]}\n\n"
            f"CODICE ORIGINALE:\n{original_code}"
        )

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            print("[SELF_HEALER] GROQ_API_KEY mancante, impossibile generare patch")
            return

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": self._HEAL_PROMPT},
                            {"role": "user", "content": user_msg},
                        ],
                        "temperature": 0.05,
                        "max_tokens": 2000,
                    },
                )
                patched_code = resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[SELF_HEALER] Errore LLM: {e}")
            return

        # Rimuovi markdown fences se presenti
        patched_code = re.sub(r"```(?:python)?\s*", "", patched_code).strip()

        # Validazione sintattica
        try:
            ast.parse(patched_code)
        except SyntaxError as e:
            print(f"[SELF_HEALER] Patch non valida (SyntaxError): {e}")
            return

        # Validazione strutturale: la patch deve contenere le stesse classi del sorgente
        try:
            orig_classes = {n.name for n in ast.walk(ast.parse(original_code)) if isinstance(n, ast.ClassDef)}
            patch_classes = {n.name for n in ast.walk(ast.parse(patched_code)) if isinstance(n, ast.ClassDef)}
            if not orig_classes.intersection(patch_classes):
                print(f"[SELF_HEALER] Patch non contiene classi originali {orig_classes}")
                return
        except Exception:
            return

        # Scrivi in plugins/<tool_name>_tool.py per hot-reload
        os.makedirs("plugins", exist_ok=True)
        final_path = os.path.join("plugins", f"{tool_name}_tool.py")
        with open(final_path, "w", encoding="utf-8") as f:
            f.write(patched_code)

        print(f"[SELF_HEALER] Patch salvata in {final_path} — hot-reload in corso")
