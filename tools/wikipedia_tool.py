"""wikipedia_tool.py - Ricerca su Wikipedia"""

import wikipedia


class WikipediaTool:
    def initialize(self):
        wikipedia.set_lang("it")

    def execute(self, action: dict) -> dict:
        query = (
            action.get("query")
            or action.get("q")
            or action.get("topic")
            or action.get("title")
            or action.get("value")
            or action.get("input")
        )

        parametro = action.get("parametro")

        if not query and isinstance(parametro, dict):
            query = (
                parametro.get("query")
                or parametro.get("q")
                or parametro.get("topic")
                or parametro.get("title")
                or parametro.get("value")
            )

        if not query and isinstance(parametro, str):
            query = parametro

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

        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
            }
