"""wikipedia_tool.py - Ricerca su Wikipedia"""

import json
from urllib.parse import quote

import requests
import wikipedia

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
            return self._fallback_rest_summary(query, sentences)

        except Exception as e:
            return {
                "status": "error",
                "message": f"Wikipedia non disponibile: {e}",
            }

    def _fallback_rest_summary(self, query: str, sentences: int) -> dict:
        try:
            url = f"https://it.wikipedia.org/api/rest_v1/page/summary/{quote(query.replace(' ', '_'))}"
            response = requests.get(url, headers={"User-Agent": "MAYA/1.0"}, timeout=8)
            response.raise_for_status()
            data = response.json()
            summary = str(data.get("extract") or "").strip()
            if not summary:
                return {
                    "status": "error",
                    "message": f"Nessun riassunto Wikipedia trovato per '{query}'.",
                }
            parts = _split_sentences(summary)
            if parts:
                summary = " ".join(parts[:sentences]).strip()
            return {
                "status": "ok",
                "message": summary,
                "query": query,
                "source": "wikipedia-rest",
            }
        except Exception:
            return {
                "status": "error",
                "message": "Wikipedia non disponibile: risposta non valida dal servizio.",
            }


def _split_sentences(text: str) -> list[str]:
    import re

    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
