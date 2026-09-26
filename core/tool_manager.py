"""
tool_manager.py - Gestore centrale dei tool
Riceve azioni dal planner e le instrada al tool corretto.
"""

import asyncio
import importlib
import os

from .token_juice import compress_tool_output

_TOOL_SPECS = {
    "system": ("tools.system_tool", "SystemTool"),
    "calendar": ("tools.calendar_tool", "CalendarTool"),
    "weather": ("tools.weather_tool", "WeatherTool"),
    "news": ("tools.news_tool", "NewsTool"),
    "notes": ("tools.notes_tool", "NotesTool"),
    "timer": ("tools.timer_tool", "TimerTool"),
    "search": ("tools.search_tool", "SearchTool"),
    "spotify": ("tools.spotify_tool", "SpotifyTool"),
    "display": ("tools.display_tool", "DisplayTool"),
    "sys_monitor": ("tools.sys_monitor_tool", "SysMonitorTool"),
    "mqtt": ("tools.mqtt_tool", "MqttTool"),
    "browser": ("tools.browser_tool", "BrowserTool"),
    "home_assistant": ("tools.home_assistant_tool", "HomeAssistantTool"),
}


class ToolManager:
    """
    Registro e router di tutti i tool del sistema.
    Aggiungere un nuovo tool = aggiungere una riga nel registro.
    """

    def __init__(self):
        self.tools = {}

    def register_tool(self, name: str, tool_instance: any):
        """Registra e inizializza un tool a runtime."""
        try:
            if hasattr(tool_instance, "initialize"):
                tool_instance.initialize()
            self.tools[name] = tool_instance
            return True
        except Exception as e:
            print(f"  [x] Errore registrazione tool '{name}': {e}")
            return False

    def unregister_tool(self, name: str):
        """Rimuove un tool dal registro."""
        if name in self.tools:
            del self.tools[name]
            return True
        return False

    def initialize(self):
        """Istanzia i tool disponibili senza rendere obbligatorie le integrazioni opzionali."""
        self.tools = {"none": _NoOpTool()}
        for name, (module_name, class_name) in _TOOL_SPECS.items():
            try:
                module = importlib.import_module(module_name)
                self.tools[name] = getattr(module, class_name)()
            except Exception as exc:
                print(f"  [x] Tool '{name}' non disponibile: {exc}")

        if os.getenv("NETWORK_TOOL_ENABLED", "false").strip().lower() in ("1", "true", "yes"):
            try:
                module = importlib.import_module("tools.network_tool")
                self.tools["network"] = module.NetworkTool()
            except Exception as exc:
                print(f"  [x] Tool 'network' non disponibile: {exc}")
        else:
            print("[TOOLS] network disattivato (NETWORK_TOOL_ENABLED=false).")

        # Inizializza ogni tool
        for name, tool in self.tools.items():
            try:
                tool.initialize()
            except Exception as e:
                print(f"  [x] Tool '{name}' errore init: {e}")

        print(f"[TOOLS] {len(self.tools)} tool inizializzati.")

    async def execute(self, action: dict) -> dict:
        """
        Esegue un'azione sul tool corretto con unwrapping automatico dei parametri.
        """
        tool_name = action.get("tool", "none")
        tool = self.tools.get(tool_name)

        if tool is None:
            return {"status": "error", "message": f"Tool '{tool_name}' non trovato"}

        # UNWRAPPING: Se i parametri sono dentro 'parametro', portiamoli al primo livello
        # Questo garantisce compatibilità con i nuovi modelli che impacchettano i dati.
        full_action = action.copy()
        if "parametro" in action and isinstance(action["parametro"], dict):
            full_action.update(action["parametro"])

        try:
            if hasattr(tool, "execute_async") and asyncio.iscoroutinefunction(tool.execute_async):
                result = await tool.execute_async(full_action)
            elif asyncio.iscoroutinefunction(tool.execute):
                result = await tool.execute(full_action)
            else:
                result = tool.execute(full_action)
            # Comprimi il campo message prima che arrivi al context LLM
            if isinstance(result, dict) and "message" in result:
                result["message"] = compress_tool_output(tool_name, result["message"])
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}


class _NoOpTool:
    """Tool vuoto: non fa nulla, utile per risposte solo testuali."""

    def initialize(self):
        pass

    def execute(self, action: dict) -> dict:
        return {"status": "ok", "message": action.get("response", "")}
