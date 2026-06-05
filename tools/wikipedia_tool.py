"""wikipedia_tool.py - Ricerca su Wikipedia"""

import wikipedia
import json

from tools.param_utils import resolve_alias


class WikipediaTool:
    def initialize(self):
        wikipedia.set_lang("it")

    def execute(self, action: dict) -> dict:
        query = resolve_alias(action, ("query", "q", "topic", "title", "value", "input"), allow_legacy_string=True)

        if not query:
            return {
                "status": "error",
                "message": "Nessuna query fornita per Wikipedia.",
            }

        query = str(query).strip()

        if not query:
            return {
                "status": "error",
                "message": "Query Wikipedia vuota.",
            }

        try:
            sentences = int(action.get("sentences", 4))
            summary = wikipedia.summary(query, sentences=sentences, auto_suggest=True)

            return {
                "status": "ok",
                "message": summary,
                "query": query,
            }

        except wikipedia.exceptions.DisambiguationError as e:
            return {
                "status": "error",
                "message": ("Termine ambiguo. Forse intendevi: " + ", ".join(e.options[:5])),
                "options": e.options[:5],
            }

        except wikipedia.exceptions.PageError:
            return {
                "status": "error",
                "message": f"Nessuna pagina trovata per '{query}'.",
            }

        except json.JSONDecodeError:
            return {
                "status": "error",
                "message": "Wikipedia non disponibile: risposta non valida dal servizio.",
            }

        except Exception as e:
            return {
                "status": "error",
                "message": f"Wikipedia non disponibile: {e}",
            }
