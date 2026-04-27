"""
search_tool.py - Ricerca Web tramite DuckDuckGo
"""

from duckduckgo_search import DDGS


class SearchTool:
    def initialize(self):
        pass

    def execute(self, action: dict) -> dict:
        query = action.get("query") or action.get("command") or action.get("text", "")
        if not query:
            return {"status": "error", "message": "Nessuna query di ricerca."}

        try:
            with DDGS() as ddgs:
                results = list(
                    ddgs.text(
                        query, region="it-it", safesearch="moderate", max_results=3
                    )
                )

            if not results:
                return {"status": "error", "message": "Nessun risultato trovato."}

            msg = f"Risultati per '{query}':\n"
            for r in results:
                msg += f"- {r['title']}: {r['body']}\n"

            return {"status": "ok", "message": msg.strip()}
        except Exception as e:
            return {"status": "error", "message": str(e)}
