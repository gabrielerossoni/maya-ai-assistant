import os
import ast

class CodeGeneratorTool:
    """Tool che permette a Maya di generare e registrare nuovi tool a runtime."""

    def initialize(self):
        self.plugins_dir = "plugins"
        os.makedirs(self.plugins_dir, exist_ok=True)

    async def execute(self, action: dict) -> dict:
        params = action.get("parametro", action)
        filename = params.get("filename")
        code = params.get("code")

        if not filename or not code:
            return {"status": "error", "message": "Mancano 'filename' o 'code'."}

        if not filename.endswith(".py"):
            filename += ".py"

        # Validazione sintattica base del codice Python
        try:
            ast.parse(code)
        except SyntaxError as e:
            return {"status": "error", "message": f"Errore di sintassi nel codice generato: {e}"}

        filepath = os.path.join(self.plugins_dir, filename)
        
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code)
            
            return {
                "status": "ok", 
                "message": f"Tool '{filename}' generato e salvato in {self.plugins_dir}. Il caricamento avverrà automaticamente via Hot-Reload."
            }
        except Exception as e:
            return {"status": "error", "message": f"Errore durante il salvataggio del file: {e}"}
