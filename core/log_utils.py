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
        
        # Messaggi espliciti per l'utente (usando user_log o [USER])
        if msg_clean.startswith("[USER]"):
            should_broadcast = True
            log_level = "info"
            display_text = msg_clean.replace("[USER]", "").strip()
        
        # Risposte di MAYA
        elif msg_clean.startswith("MAYA >"):
            should_broadcast = True
            log_level = "ok"
            display_text = msg_clean.replace("MAYA > ", "🤖 MAYA: ")
        
        # Errori critici (solo se contengono il tag [USER_ERR])
        elif "[USER_ERR]" in msg_clean:
            should_broadcast = True
            log_level = "warn"
            display_text = msg_clean.replace("[USER_ERR]", "").strip()
        
        if should_broadcast:
            try:
                loop = getattr(self.manager, "loop", None)
                # Non usare loop.is_running() da altri thread: può essere False in modo spurio.
                if loop is None:
                    return
                asyncio.run_coroutine_threadsafe(
                    self.manager.broadcast(
                        {
                            "type": "log",
                            "text": display_text,
                            "level": log_level,
                        }
                    ),
                    loop,
                )
            except Exception:
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

def user_log(message: str, is_error: bool = False):
    """
    Invia un messaggio che verrà mostrato sulla dashboard dell'utente.
    Viene comunque stampato nel terminale.
    """
    prefix = "[USER_ERR]" if is_error else "[USER]"
    print(f"{prefix} {message}")
