"""
notes_tool.py - Gestione appunti e todo
"""
import json
import os

class NotesTool:
    def __init__(self):
        self.filepath = os.path.join(os.path.dirname(__file__), "..", "data", "notes.json")

    def initialize(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        if not os.path.exists(self.filepath):
            with open(self.filepath, "w") as f:
                json.dump({"todo": [], "notes": []}, f)

    def execute(self, action: dict) -> dict:
        operation = action.get("operation", "list") # add, remove, list
        item = action.get("item", "")
        category = action.get("category", "todo")

        try:
            with open(self.filepath, "r") as f:
                data = json.load(f)
            
            if category not in data:
                data[category] = []

            if operation == "add":
                if item:
                    data[category].append(item)
                    msg = f"Aggiunto '{item}' a {category}."
                else:
                    return {"status": "error", "message": "Nessun elemento da aggiungere."}
            elif operation == "remove":
                if item in data[category]:
                    data[category].remove(item)
                    msg = f"Rimosso '{item}' da {category}."
                else:
                    msg = f"Elemento '{item}' non trovato in {category}."
            elif operation == "list":
                items = data[category]
                if not items:
                    msg = f"La lista {category} è vuota."
                else:
                    msg = f"Lista {category}:\n" + "\n".join(f"- {i}" for i in items)
            else:
                return {"status": "error", "message": f"Operazione '{operation}' non valida."}

            with open(self.filepath, "w") as f:
                json.dump(data, f, indent=4)

            return {"status": "ok", "message": msg}
        except Exception as e:
            return {"status": "error", "message": str(e)}
