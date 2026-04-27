import sys
import asyncio

class DashboardLogFilter:
    """
    Filtra i log e invia solo quelli rilevanti alla dashboard.
    - Richieste dell'utente (iniziano con "Richiesta:")
    - Risposte di MAYA (iniziano con "MAYA >")
    - I log tecnici rimangono solo nel terminale
    """
    def __init__(self, original_stdout, ws_manager):
        self.terminal = original_stdout
        self.manager = ws_manager

    def write(self, message):
        # Sempre scrivi nel terminale
        self.terminal.write(message)
        
        msg_clean = message.strip()
        if not msg_clean:
            return
        
        # Filtra i messaggi che vanno sulla dashboard
        should_broadcast = False
        log_level = "info"
        display_text = msg_clean
        
        # Richieste dell'utente
        if msg_clean.startswith("Richiesta:"):
            should_broadcast = True
            log_level = "info"
            display_text = msg_clean.replace("Richiesta: ", "👤 ")
        
        # Risposte di MAYA
        elif msg_clean.startswith("MAYA >"):
            should_broadcast = True
            log_level = "ok"
            display_text = msg_clean.replace("MAYA > ", "🤖 MAYA: ")
        
        # Nucleo connesso
        elif "Nucleo Maya Connesso" in msg_clean:
            should_broadcast = True
            log_level = "ok"
        
        # Errori critici
        elif any(err in msg_clean for err in ["[ERRORE]", "Error:", "Exception:"]):
            should_broadcast = True
            log_level = "warn"
        
        if should_broadcast:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.manager.broadcast({
                        "type": "log", 
                        "text": display_text, 
                        "level": log_level
                    }))
            except:
                pass

    def flush(self):
        self.terminal.flush()

    def isatty(self):
        """Necessario per uvicorn e altri logger che controllano se è un terminale interattivo."""
        return self.terminal.isatty()

    def fileno(self):
        """Necessario per alcuni sistemi di logging di basso livello."""
        return self.terminal.fileno()

def setup_dashboard_log_filter(manager):
    """Sostituisce sys.stdout con il filtro dashboard."""
    sys.stdout = DashboardLogFilter(sys.stdout, manager)
