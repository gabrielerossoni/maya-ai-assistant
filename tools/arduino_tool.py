"""
tools/arduino_tool.py
Comunica con Arduino via porta seriale USB.
Invia stringhe di comando, riceve conferma.
"""

import time
import os

# Importazione opzionale: se pyserial non è installato, entra in modalità simulazione
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    print("[ARDUINO] pyserial non installato. Modalità simulazione attiva.")

# ──────────────────────────────────────────────
# CONFIGURAZIONE
# ──────────────────────────────────────────────
BAUD_RATE    = int(os.getenv("ARDUINO_BAUD_RATE", 9600))
TIMEOUT_SEC  = 2
# Lascia AUTO per ricerca automatica, oppure specifica es. "COM3" / "/dev/ttyUSB0"
SERIAL_PORT  = os.getenv("ARDUINO_PORT", "AUTO")

# Comandi validi che Arduino riconosce
VALID_COMMANDS = {
    "LIGHT_ON", "LIGHT_OFF",
    "RELAY_ON", "RELAY_OFF",
    "SERVO_OPEN", "SERVO_CLOSE",
    "STATUS",
}


class ArduinoTool:
    """Tool per comunicazione seriale con Arduino."""

    def __init__(self):
        self.connection = None
        self.simulated  = not SERIAL_AVAILABLE
        self.sim_state  = {}   # stato simulato dei pin

    def initialize(self):
        """Tenta di aprire la porta seriale. Se fallisce, passa a simulazione."""
        if not SERIAL_AVAILABLE:
            self.simulated = True
            return

        port = self._find_port() if SERIAL_PORT == "AUTO" else SERIAL_PORT

        if port is None:
            print("[ARDUINO] Nessuna porta trovata. Modalità simulazione attiva.")
            self.simulated = True
            return

        try:
            self.connection = serial.Serial(port, BAUD_RATE, timeout=TIMEOUT_SEC)
            time.sleep(2)  # Attendi reset Arduino
            print(f"[ARDUINO] Connesso su {port} a {BAUD_RATE} baud.")
            self.simulated = False
        except serial.SerialException as e:
            print(f"[ARDUINO] Errore apertura porta: {e}. Simulazione attiva.")
            self.simulated = True

    def _find_port(self) -> str | None:
        """Cerca automaticamente la porta con Arduino."""
        for port_info in serial.tools.list_ports.comports():
            # Arduino di solito appare come CH340, ATmega, o con "Arduino" nel nome
            desc = (port_info.description or "").lower()
            if any(k in desc for k in ["arduino", "ch340", "atmega", "usb serial"]):
                print(f"[ARDUINO] Trovato: {port_info.device} - {port_info.description}")
                return port_info.device
        return None

    def execute(self, action: dict) -> dict:
        """
        Invia un comando ad Arduino e attende risposta.
        action: {"tool": "arduino", "command": "LIGHT_ON"}
        """
        command = action.get("command", "").strip().upper()

        if command not in VALID_COMMANDS:
            return {"status": "error", "message": f"Comando '{command}' non valido"}

        if self.simulated:
            return self._simulate(command)

        return self._send_command(command)

    def _send_command(self, command: str) -> dict:
        """Invia il comando alla porta seriale."""
        try:
            self.connection.write(f"{command}\n".encode("utf-8"))
            self.connection.flush()

            # Attendi conferma da Arduino (es: "OK:LIGHT_ON")
            response = self.connection.readline().decode("utf-8").strip()
            print(f"[ARDUINO] Arduino risponde: '{response}'")

            if response.startswith("OK"):
                return {"status": "ok", "command": command, "response": response}
            else:
                return {"status": "warning", "command": command, "response": response}

        except serial.SerialException as e:
            return {"status": "error", "message": str(e)}

    def _simulate(self, command: str) -> dict:
        """Simula l'esecuzione del comando senza Arduino fisico."""
        # Aggiorna stato simulato
        state_map = {
            "LIGHT_ON":    ("light",  "ON"),
            "LIGHT_OFF":   ("light",  "OFF"),
            "RELAY_ON":    ("relay",  "ON"),
            "RELAY_OFF":   ("relay",  "OFF"),
            "SERVO_OPEN":  ("servo",  "OPEN"),
            "SERVO_CLOSE": ("servo",  "CLOSED"),
        }

        if command in state_map:
            component, state = state_map[command]
            self.sim_state[component] = state
            print(f"[ARDUINO SIM] {component} → {state}")

        return {
            "status": "ok",
            "command": command,
            "simulated": True,
            "state": self.sim_state
        }

    def close(self):
        """Chiudi la connessione seriale."""
        if self.connection and self.connection.is_open:
            self.connection.close()
