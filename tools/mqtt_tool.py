import paho.mqtt.client as mqtt
import json
import os

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC_PREFIX = "maya/rooms/"

class MqttTool:
    """Tool per la gestione multi-room via MQTT."""

    def __init__(self):
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

    def initialize(self):
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
            self.client.loop_start()
            print(f"[MQTT] Connesso al broker {MQTT_BROKER}:{MQTT_PORT}")
        except Exception as e:
            print(f"[MQTT] Errore connessione broker: {e}")

    async def execute(self, action: dict) -> dict:
        """
        Invia un comando a una stanza specifica.
        action: {"tool": "mqtt", "room": "kitchen", "device": "light", "state": "ON"}
        """
        room = action.get("room", "all")
        device = action.get("device", "unknown")
        state = action.get("state", "TOGGLE")
        
        topic = f"{MQTT_TOPIC_PREFIX}{room}/{device}"
        payload = json.dumps({"state": state, "sender": "maya_core"})
        
        try:
            result = self.client.publish(topic, payload)
            result.wait_for_publish()
            return {
                "status": "ok",
                "message": f"Comando '{state}' inviato a {device} in stanza '{room}'",
                "topic": topic
            }
        except Exception as e:
            return {"status": "error", "message": f"Errore MQTT: {e}"}

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()
