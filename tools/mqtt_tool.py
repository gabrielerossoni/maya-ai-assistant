import paho.mqtt.client as mqtt
import json
import os
import asyncio

MQTT_BROKER     = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT       = int(os.getenv("MQTT_PORT", 1883))
TOPIC_PREFIX    = "maya/rooms/"

class MqttTool:
    """Tool per la gestione multi-room via MQTT (bidirectional con WebSocket broadcast)."""

    def __init__(self):
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self._ws_manager = None   # iniettato da main.py
        self._loop       = None   # event loop asyncio

    def set_ws_manager(self, ws_manager, loop):
        """Chiamato in lifespan dopo che il loop è pronto."""
        self._ws_manager = ws_manager
        self._loop       = loop
        print("[MQTT] WebSocketManager iniettato per broadcast.")

    def initialize(self):
        """Setup MQTT callbacks e connessione."""
        self.client.on_message = self._on_message
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.client.loop_start()
            print(f"[MQTT] Connesso al broker {MQTT_BROKER}:{MQTT_PORT}")
        except Exception as e:
            print(f"[MQTT] Errore connessione broker: {e}")

    def _on_connect(self, client, userdata, flags, rc, props=None):
        """Callback: sottoscrizione ai topic state/telemetry di tutte le stanze."""
        if rc == 0:
            # Subscribe a tutti i topic state e telemetry di tutte le stanze
            client.subscribe(f"{TOPIC_PREFIX}+/state",     qos=1)
            client.subscribe(f"{TOPIC_PREFIX}+/telemetry", qos=0)
            print(f"[MQTT] Connesso, in ascolto su {TOPIC_PREFIX}+/state|telemetry")
        else:
            print(f"[MQTT] Connessione fallita, code {rc}")

    def _on_disconnect(self, client, userdata, rc, props=None):
        """Callback: disconnessione."""
        if rc != 0:
            print(f"[MQTT] Disconnessione non attesa, code {rc}")

    def _on_message(self, client, userdata, msg):
        """Riceve stato/telemetria da Arduino e lo propaga via WebSocket."""
        if not self._ws_manager or not self._loop:
            print("[MQTT] WebSocketManager non iniettato, ignoro messaggio")
            return
        
        try:
            payload = json.loads(msg.payload.decode())
            parts = msg.topic.split("/")   # maya/rooms/<room>/<type>
            
            if len(parts) < 4:
                return
            
            room = parts[2]
            kind = parts[3]   # "state" o "telemetry"

            if kind == "state":
                # Payload: {"state": {"light": bool, "relay": bool, "servo": int, "rgb": [r,g,b], "buzzer": bool}}
                state = payload.get("state", {})
                broadcast_payload = {
                    "type": "arduino_state",
                    "room": room,
                    "led": "on" if state.get("light") else "off",
                    "relay": "on" if state.get("relay") else "off",
                    "servo": state.get("servo", 0),
                    "rgb": state.get("rgb", [0, 0, 0]),
                    "buzzer": state.get("buzzer", False),
                }
                
            elif kind == "telemetry":
                # Payload: {"telemetry": {"temp": float, "humidity": float, "uptime_ms": long}}
                broadcast_payload = {
                    "type": "arduino_telemetry",
                    "room": room,
                    "data": payload.get("telemetry", {}),
                }
            else:
                return

            # Broadcast al WebSocket in modo thread-safe
            asyncio.run_coroutine_threadsafe(
                self._ws_manager.broadcast(broadcast_payload),
                self._loop
            )
            print(f"[MQTT] Broadcast {kind} da stanza '{room}' via WebSocket")
            
        except json.JSONDecodeError:
            print(f"[MQTT] Errore parsing JSON: {msg.payload}")
        except Exception as e:
            print(f"[MQTT] Errore processing messaggio: {e}")

    async def execute(self, action: dict) -> dict:
        """
        Invia un comando a una stanza specifica.
        Supporta 2 formati:
        - Old: {"tool": "mqtt", "room": "kitchen", "device": "light", "state": "ON"}
        - New: {"tool": "mqtt", "op": "SET", "target": "light", "value": 1, "room": "studio"}
        """
        room   = action.get("room", os.getenv("MQTT_DEFAULT_ROOM", "studio"))
        
        # Format detection: nuovo è più simile a Arduino
        if "op" in action and "target" in action:
            # Nuovo formato (simile a Arduino protocol)
            op     = action.get("op", "SET")
            target = action.get("target", "light")
            value  = action.get("value", 0)
            
            cmd_payload = json.dumps({
                "cmd": op,
                "target": target,
                "value": value,
                "id": 1
            })
        else:
            # Vecchio formato per backward compatibility
            device = action.get("device", "light")
            state  = action.get("state", "TOGGLE")
            
            cmd_payload = json.dumps({
                "device": device,
                "state": state,
                "sender": "maya_core"
            })
        
        topic = f"{TOPIC_PREFIX}{room}/cmd"
        
        try:
            result = self.client.publish(topic, cmd_payload, qos=1, retain=False)
            result.wait_for_publish(timeout=2.0)
            return {
                "status": "ok",
                "message": f"Comando inviato a stanza '{room}' (QoS 1)",
                "topic": topic
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"Errore MQTT publish: {e}"
            }

    def close(self):
        """Chiudi connessione MQTT."""
        self.client.loop_stop()
        self.client.disconnect()
        print("[MQTT] Disconnesso.")
