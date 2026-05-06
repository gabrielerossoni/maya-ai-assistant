"""
tool_manager.py - Gestore centrale dei tool
Riceve azioni dal planner e le instrada al tool corretto.
"""

import asyncio
from tools.arduino_tool import ArduinoTool
from tools.network_tool import NetworkTool
from tools.system_tool import SystemTool
from tools.calendar_tool import CalendarTool
from tools.weather_tool import WeatherTool
from tools.news_tool import NewsTool
from tools.wikipedia_tool import WikipediaTool
from tools.notes_tool import NotesTool
from tools.trading_tool import TradingTool
from tools.timer_tool import TimerTool
from tools.translate_tool import TranslateTool
from tools.search_tool import SearchTool
from tools.spotify_tool import SpotifyTool
from tools.sys_monitor_tool import SysMonitorTool
from tools.code_generator_tool import CodeGeneratorTool
from tools.mqtt_tool import MqttTool


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
            print(f"  [✓] Tool '{name}' registrato/aggiornato")
            return True
        except Exception as e:
            print(f"  [✗] Errore registrazione tool '{name}': {e}")
            return False

    def unregister_tool(self, name: str):
        """Rimuove un tool dal registro."""
        if name in self.tools:
            del self.tools[name]
            print(f"  [-] Tool '{name}' rimosso")
            return True
        return False

    def initialize(self):
        """Istanzia e registra tutti i tool."""
        self.tools = {
            "arduino": ArduinoTool(),
            "network": NetworkTool(),
            "system": SystemTool(),
            "calendar": CalendarTool(),
            "weather": WeatherTool(),
            "news": NewsTool(),
            "wikipedia": WikipediaTool(),
            "notes": NotesTool(),
            "trading": TradingTool(),
            "timer": TimerTool(),
            "translate": TranslateTool(),
            "search": SearchTool(),
            "spotify": SpotifyTool(),
            "sys_monitor": SysMonitorTool(),
            "code_generator": CodeGeneratorTool(),
            "mqtt": MqttTool(),
            "none": _NoOpTool(),
        }

        # Inizializza ogni tool
        for name, tool in self.tools.items():
            try:
                tool.initialize()
                print(f"  [✓] Tool '{name}' inizializzato")
            except Exception as e:
                print(f"  [✗] Tool '{name}' errore init: {e}")

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
            # Ogni tool ha un metodo execute(action) asincrono
            if asyncio.iscoroutinefunction(tool.execute):
                result = await tool.execute(full_action)
            else:
                result = tool.execute(full_action)
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}


class _NoOpTool:
    """Tool vuoto: non fa nulla, utile per risposte solo testuali."""

    def initialize(self):
        pass

    def execute(self, action: dict) -> dict:
        return {"status": "ok", "message": action.get("response", "")}
