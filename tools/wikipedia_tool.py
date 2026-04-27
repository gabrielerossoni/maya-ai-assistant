"""
wikipedia_tool.py - Ricerca su Wikipedia
"""
import wikipedia

class WikipediaTool:
    def initialize(self):
        wikipedia.set_lang("it")

    def execute(self, action: dict) -> dict:
        query = action.get("query", "")
        if not query:
            return {"status": "error", "message": "Nessuna query fornita per Wikipedia."}
        
        try:
            summary = wikipedia.summary(query, sentences=2)
            return {"status": "ok", "message": summary}
        except wikipedia.exceptions.DisambiguationError as e:
            return {"status": "ok", "message": f"Termine ambiguo. Forse intendevi: {', '.join(e.options[:3])}?"}
        except wikipedia.exceptions.PageError:
            return {"status": "error", "message": f"Nessuna pagina trovata per '{query}'."}
        except Exception as e:
            return {"status": "error", "message": str(e)}
