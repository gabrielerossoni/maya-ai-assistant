"""
timer_tool.py - Impostazione di timer
"""
import asyncio

class TimerTool:
    def initialize(self):
        pass

    async def _run_timer(self, seconds: int, message: str):
        await asyncio.sleep(seconds)
        # Qui potremmo integrare una notifica di sistema reale
        # o inviare un messaggio WebSocket al front-end se presente.
        print(f"\n[ALARM] DRIIIN! Timer scaduto: {message}\n")

    async def execute(self, action: dict) -> dict:
        minutes = action.get("minutes", 0)
        seconds = action.get("seconds", 0)
        message = action.get("message", "Timer scaduto!")

        total_seconds = (minutes * 60) + seconds
        if total_seconds <= 0:
            return {"status": "error", "message": "Durata del timer non valida."}

        # Esegue il timer in background
        asyncio.create_task(self._run_timer(total_seconds, message))

        return {"status": "ok", "message": f"Timer impostato per {minutes} minuti e {seconds} secondi."}
