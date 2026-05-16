/*
 * MAYA Arduino Controller — JSON Protocol + MQTT (Uno R4 WiFi)
 * ─────────────────────────────────────────────────────────────
 * ArduinoJson 6.x | WiFiS3 | PubSubClient
 * 115200 baud (Serial) | MQTT Topics: maya/rooms/<room>/{cmd,state,telemetry}
 *
 * Pin map:
 *   LED      → 13  |  Relay  →  7
 *   Servo    →  9  |  DHT11  →  4
 *   RGB R    →  5  |  RGB G  →  6  |  RGB B → 3
 *   Buzzer   →  8
 *
 * Incoming Serial (one JSON line, \n-terminated):
 *   {"id":<int>,"cmd":"SET"|"GET","target":"light"|"relay"|"servo"|
 *    "rgb"|"buzzer"|"sensor_read","value":<int|obj>}
 *
 * MQTT Topics (subscribe to apply commands, publish state/telemetry):
 *   maya/rooms/<room>/cmd         → ricevere comando JSON
 *   maya/rooms/<room>/state       → pubblicare stato (light, relay, servo, rgb, buzzer)
 *   maya/rooms/<room>/telemetry   → pubblicare sensori (temp, humidity, uptime)
 *
 * Response/State format:
 *   {"id":<int>,"status":"ok"|"error",
 *    "state":{"light":bool,"relay":bool,"servo":int,
 *             "rgb":[r,g,b],"buzzer":bool}}
 */

#include <ArduinoJson.h>
#include <Servo.h>
#include <DHT.h>
#include <WiFiS3.h>
#include <PubSubClient.h>

// ── WiFi Credentials ──────────────────────────
const char* SSID        = "";    // Configura il tuo SSID
const char* WIFI_PASS   = "";    // Configura la password
const char* MQTT_BROKER = "localhost";  // Broker locale (default)
const int   MQTT_PORT   = 1883;
const char* MQTT_ROOM   = "studio";     // Stanza di default
char        MQTT_CLIENT_ID[32];

// ── Pin definitions ───────────────────────────
const int LED_PIN   = 13;
const int RELAY_PIN =  7;
const int SERVO_PIN =  9;
const int RGB_R_PIN =  5;
const int RGB_G_PIN =  6;
const int RGB_B_PIN =  3;
const int BUZZ_PIN  =  8;
const int DHT_PIN   =  4;
#define   DHT_TYPE  DHT11

// ── State ─────────────────────────────────────
bool    lightOn  = false;
bool    relayOn  = false;
int     servoPos = 0;
uint8_t rgbR = 0, rgbG = 0, rgbB = 0;
bool    buzzerOn = false;

// ── Timing ────────────────────────────────────
unsigned long buzzStartMs      = 0;
unsigned long lastTelemetryMs  = 0;
unsigned long lastMqttConnectAttempt = 0;

const unsigned long BUZZ_DURATION_MS       = 200;
const unsigned long TELEMETRY_INTERVAL     = 5000;
const unsigned long MQTT_CONNECT_INTERVAL  = 10000;

// ── MQTT & WiFi ───────────────────────────────
WiFiClient espClient;
PubSubClient mqttClient(espClient);

// ── Objects ────────────────────────────────────
Servo myServo;
DHT   dht(DHT_PIN, DHT_TYPE);

// ── Prototypes ────────────────────────────────
void buildState(JsonObject state);
void sendResponse(int id, bool ok);
void sendError(int id, const char* msg);
void sendTelemetry();
void applyRGBInt(long color);
void setupWiFi();
void connectMQTT();
void mqttCallback(char* topic, byte* payload, unsigned int length);
void publishState();
void handleMqttCommand(JsonDocument& cmd);

// ── Setup ─────────────────────────────────────
void setup() {
  Serial.begin(115200);

  pinMode(LED_PIN,   OUTPUT);
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUZZ_PIN,  OUTPUT);
  pinMode(RGB_R_PIN, OUTPUT);
  pinMode(RGB_G_PIN, OUTPUT);
  pinMode(RGB_B_PIN, OUTPUT);

  digitalWrite(LED_PIN,   LOW);
  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(BUZZ_PIN,  LOW);
  analogWrite(RGB_R_PIN, 0);
  analogWrite(RGB_G_PIN, 0);
  analogWrite(RGB_B_PIN, 0);

  myServo.attach(SERVO_PIN);
  myServo.write(0);

  dht.begin();

  // Generate unique MQTT client ID
  snprintf(MQTT_CLIENT_ID, sizeof(MQTT_CLIENT_ID), "maya_arduino_%lX", micros());

  // Setup WiFi & MQTT (non-blocking attempt)
  setupWiFi();
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
}

// ── Loop ──────────────────────────────────────
void loop() {
  // 1. WiFi/MQTT keep-alive
  if (WiFi.status() == WL_CONNECTED) {
    if (!mqttClient.connected()) {
      if (millis() - lastMqttConnectAttempt >= MQTT_CONNECT_INTERVAL) {
        lastMqttConnectAttempt = millis();
        connectMQTT();
      }
    } else {
      mqttClient.loop();
    }
  } else {
    // Tenta riconnessione WiFi ogni 10s
    static unsigned long lastWiFiAttempt = 0;
    if (millis() - lastWiFiAttempt >= 10000) {
      lastWiFiAttempt = millis();
      setupWiFi();
    }
  }

  // 2. Handle incoming serial command (fallback/direct control)
  if (Serial.available() > 0) {
    String line = Serial.readStringUntil('\n');
    line.trim();

    if (line.length() > 0) {
      StaticJsonDocument<256> doc;
      DeserializationError err = deserializeJson(doc, line);

      if (err) {
        sendError(-1, "parse_fail");
      } else {
        handleSerialCommand(doc);
      }
    }
  }

  // 3. Non-blocking buzzer auto-off
  if (buzzerOn && (millis() - buzzStartMs >= BUZZ_DURATION_MS)) {
    buzzerOn = false;
    digitalWrite(BUZZ_PIN, LOW);
  }

  // 4. Periodic telemetry (MQTT + Serial)
  if (millis() - lastTelemetryMs >= TELEMETRY_INTERVAL) {
    lastTelemetryMs = millis();
    sendTelemetry();
    if (WiFi.status() == WL_CONNECTED && mqttClient.connected()) {
      publishTelemetry();
    }
  }
}

// ── WiFi Setup ────────────────────────────────
void setupWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;  // Already connected
  
  if (strlen(SSID) == 0) {
    Serial.println("[WiFi] SSID non configurato — MQTT disabilitato");
    return;
  }

  Serial.print("[WiFi] Connessione a ");
  Serial.println(SSID);
  
  WiFi.begin(SSID, WIFI_PASS);
  
  int timeout = 0;
  while (WiFi.status() != WL_CONNECTED && timeout < 20) {
    delay(500);
    Serial.print(".");
    timeout++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("\n[WiFi] Connesso! IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n[WiFi] Connessione fallita");
  }
}

// ── MQTT Connect ──────────────────────────────
void connectMQTT() {
  if (!WiFi.isConnected()) return;
  
  if (mqttClient.connect(MQTT_CLIENT_ID)) {
    Serial.print("[MQTT] Connesso a ");
    Serial.println(MQTT_BROKER);
    
    // Subscribe a comando
    char subTopic[64];
    snprintf(subTopic, sizeof(subTopic), "maya/rooms/%s/cmd", MQTT_ROOM);
    mqttClient.subscribe(subTopic, 1);  // QoS 1
    
    Serial.print("[MQTT] Sottoscritto a: ");
    Serial.println(subTopic);
    
    // Pubblica stato iniziale
    publishState();
  } else {
    Serial.print("[MQTT] Connessione fallita, code: ");
    Serial.println(mqttClient.state());
  }
}

// ── MQTT Callback ─────────────────────────────
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  // Parse JSON comando da MQTT
  StaticJsonDocument<256> cmd;
  DeserializationError err = deserializeJson(cmd, payload, length);
  
  if (err) {
    Serial.print("[MQTT] Parse error: ");
    Serial.println(err.c_str());
    return;
  }
  
  handleMqttCommand(cmd);
}

// ── Handle MQTT Command ───────────────────────
void handleMqttCommand(JsonDocument& cmd) {
  int         id     = cmd["id"]     | -1;
  const char* cmdOp  = cmd["cmd"]    | "";
  const char* target = cmd["target"] | "";
  
  bool isSET = (strcmp(cmdOp, "SET") == 0);
  bool isGET = (strcmp(cmdOp, "GET") == 0);

  if (!isSET && !isGET) {
    sendError(id, "bad_cmd");
    return;
  }

  applyCommand(id, isSET, target, cmd);
  
  // Auto-publish stato dopo comando
  publishState();
}

// ── Handle Serial Command ──────────────────────
void handleSerialCommand(JsonDocument& doc) {
  int         id     = doc["id"]     | -1;
  const char* cmd    = doc["cmd"]    | "";
  const char* target = doc["target"] | "";

  bool isSET = (strcmp(cmd, "SET") == 0);
  bool isGET = (strcmp(cmd, "GET") == 0);

  if (!isSET && !isGET) {
    sendError(id, "bad_cmd");
    return;
  }

  applyCommand(id, isSET, target, doc);
}

// ── Apply Command (shared logic) ───────────────
void applyCommand(int id, bool isSET, const char* target, JsonDocument& doc) {
  if (strcmp(target, "light") == 0) {
    if (isSET) {
      lightOn = doc["value"].as<int>() != 0;
      digitalWrite(LED_PIN, lightOn ? HIGH : LOW);
    }
    sendResponse(id, true);

  } else if (strcmp(target, "relay") == 0) {
    if (isSET) {
      relayOn = doc["value"].as<int>() != 0;
      digitalWrite(RELAY_PIN, relayOn ? HIGH : LOW);
    }
    sendResponse(id, true);

  } else if (strcmp(target, "servo") == 0) {
    if (isSET) {
      servoPos = constrain(doc["value"].as<int>(), 0, 180);
      myServo.write(servoPos);
    }
    sendResponse(id, true);

  } else if (strcmp(target, "rgb") == 0) {
    if (isSET) {
      JsonVariant val = doc["value"];
      if (val.is<JsonObject>()) {
        rgbR = val["r"] | 0;
        rgbG = val["g"] | 0;
        rgbB = val["b"] | 0;
      } else {
        applyRGBInt(val.as<long>());
      }
      analogWrite(RGB_R_PIN, rgbR);
      analogWrite(RGB_G_PIN, rgbG);
      analogWrite(RGB_B_PIN, rgbB);
    }
    sendResponse(id, true);

  } else if (strcmp(target, "buzzer") == 0) {
    if (isSET) {
      if (doc["value"].as<int>() != 0) {
        buzzerOn    = true;
        buzzStartMs = millis();
        digitalWrite(BUZZ_PIN, HIGH);
      } else {
        buzzerOn = false;
        digitalWrite(BUZZ_PIN, LOW);
      }
    }
    sendResponse(id, true);

  } else if (strcmp(target, "sensor_read") == 0) {
    float temp = dht.readTemperature();
    float hum  = dht.readHumidity();

    StaticJsonDocument<320> resp;
    resp["id"]     = id;
    resp["status"] = "ok";
    JsonObject st  = resp.createNestedObject("state");
    buildState(st);
    if (!isnan(temp)) resp["temp"]     = temp;
    if (!isnan(hum))  resp["humidity"] = hum;
    serializeJson(resp, Serial);
    Serial.print('\n');

  } else if (strcmp(target, "status") == 0) {
    sendResponse(id, true);

  } else {
    sendError(id, "unknown_target");
  }
}

// ── Helpers ───────────────────────────────────

void buildState(JsonObject state) {
  state["light"] = lightOn;
  state["relay"] = relayOn;
  state["servo"] = servoPos;
  JsonArray rgb  = state.createNestedArray("rgb");
  rgb.add(rgbR);
  rgb.add(rgbG);
  rgb.add(rgbB);
  state["buzzer"] = buzzerOn;
}

void sendResponse(int id, bool ok) {
  StaticJsonDocument<256> doc;
  doc["id"]          = id;
  doc["status"]      = ok ? "ok" : "error";
  JsonObject state   = doc.createNestedObject("state");
  buildState(state);
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void sendError(int id, const char* msg) {
  StaticJsonDocument<96> doc;
  doc["id"]     = id;
  doc["status"] = "error";
  doc["msg"]    = msg;
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void applyRGBInt(long color) {
  rgbR = (color >> 16) & 0xFF;
  rgbG = (color >>  8) & 0xFF;
  rgbB =  color        & 0xFF;
}

void sendTelemetry() {
  float temp = dht.readTemperature();
  float hum  = dht.readHumidity();

  StaticJsonDocument<128> doc;
  JsonObject tel   = doc.createNestedObject("telemetry");
  if (!isnan(temp)) tel["temp"]     = temp;
  if (!isnan(hum))  tel["humidity"] = hum;
  tel["uptime_ms"] = (long)millis();
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void publishState() {
  if (!mqttClient.connected()) return;
  
  StaticJsonDocument<256> doc;
  JsonObject state = doc.createNestedObject("state");
  buildState(state);
  
  char topic[64];
  snprintf(topic, sizeof(topic), "maya/rooms/%s/state", MQTT_ROOM);
  
  String payload;
  serializeJson(doc, payload);
  mqttClient.publish(topic, payload.c_str(), 1, false);  // QoS 1, no retain
}

void publishTelemetry() {
  if (!mqttClient.connected()) return;
  
  float temp = dht.readTemperature();
  float hum  = dht.readHumidity();
  
  StaticJsonDocument<128> doc;
  JsonObject tel = doc.createNestedObject("telemetry");
  if (!isnan(temp)) tel["temp"]     = temp;
  if (!isnan(hum))  tel["humidity"] = hum;
  tel["uptime_ms"] = (long)millis();
  
  char topic[64];
  snprintf(topic, sizeof(topic), "maya/rooms/%s/telemetry", MQTT_ROOM);
  
  String payload;
  serializeJson(doc, payload);
  mqttClient.publish(topic, payload.c_str(), 0, false);  // QoS 0 for telemetry
}

// ── Pin definitions ───────────────────────────
const int LED_PIN   = 13;
const int RELAY_PIN =  7;
const int SERVO_PIN =  9;
const int RGB_R_PIN =  5;
const int RGB_G_PIN =  6;
const int RGB_B_PIN =  3;
const int BUZZ_PIN  =  8;
const int DHT_PIN   =  4;
#define   DHT_TYPE  DHT11

// ── State ─────────────────────────────────────
bool    lightOn  = false;
bool    relayOn  = false;
int     servoPos = 0;
uint8_t rgbR = 0, rgbG = 0, rgbB = 0;
bool    buzzerOn = false;

// ── Timing ────────────────────────────────────
unsigned long buzzStartMs      = 0;
unsigned long lastTelemetryMs  = 0;

const unsigned long BUZZ_DURATION_MS   = 200;
const unsigned long TELEMETRY_INTERVAL = 5000;

Servo myServo;
DHT   dht(DHT_PIN, DHT_TYPE);

// ── Prototypes ────────────────────────────────
void buildState(JsonObject state);
void sendResponse(int id, bool ok);
void sendError(int id, const char* msg);
void sendTelemetry();
void applyRGBInt(long color);

// ── Setup ─────────────────────────────────────
void setup() {
  Serial.begin(115200);

  pinMode(LED_PIN,   OUTPUT);
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUZZ_PIN,  OUTPUT);
  pinMode(RGB_R_PIN, OUTPUT);
  pinMode(RGB_G_PIN, OUTPUT);
  pinMode(RGB_B_PIN, OUTPUT);

  digitalWrite(LED_PIN,   LOW);
  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(BUZZ_PIN,  LOW);
  analogWrite(RGB_R_PIN, 0);
  analogWrite(RGB_G_PIN, 0);
  analogWrite(RGB_B_PIN, 0);

  myServo.attach(SERVO_PIN);
  myServo.write(0);

  dht.begin();
}

// ── Loop ──────────────────────────────────────
void loop() {
  // 1. Handle incoming serial command
  if (Serial.available() > 0) {
    String line = Serial.readStringUntil('\n');
    line.trim();

    if (line.length() > 0) {
      StaticJsonDocument<256> doc;
      DeserializationError err = deserializeJson(doc, line);

      if (err) {
        sendError(-1, "parse_fail");
      } else {
        int         id     = doc["id"]     | -1;
        const char* cmd    = doc["cmd"]    | "";
        const char* target = doc["target"] | "";

        bool isSET = (strcmp(cmd, "SET") == 0);
        bool isGET = (strcmp(cmd, "GET") == 0);

        if (!isSET && !isGET) {
          sendError(id, "bad_cmd");

        } else if (strcmp(target, "light") == 0) {
          if (isSET) {
            lightOn = doc["value"].as<int>() != 0;
            digitalWrite(LED_PIN, lightOn ? HIGH : LOW);
          }
          sendResponse(id, true);

        } else if (strcmp(target, "relay") == 0) {
          if (isSET) {
            relayOn = doc["value"].as<int>() != 0;
            digitalWrite(RELAY_PIN, relayOn ? HIGH : LOW);
          }
          sendResponse(id, true);

        } else if (strcmp(target, "servo") == 0) {
          if (isSET) {
            servoPos = constrain(doc["value"].as<int>(), 0, 180);
            myServo.write(servoPos);
          }
          sendResponse(id, true);

        } else if (strcmp(target, "rgb") == 0) {
          if (isSET) {
            JsonVariant val = doc["value"];
            if (val.is<JsonObject>()) {
              rgbR = val["r"] | 0;
              rgbG = val["g"] | 0;
              rgbB = val["b"] | 0;
            } else {
              applyRGBInt(val.as<long>());
            }
            analogWrite(RGB_R_PIN, rgbR);
            analogWrite(RGB_G_PIN, rgbG);
            analogWrite(RGB_B_PIN, rgbB);
          }
          sendResponse(id, true);

        } else if (strcmp(target, "buzzer") == 0) {
          if (isSET) {
            if (doc["value"].as<int>() != 0) {
              buzzerOn    = true;
              buzzStartMs = millis();
              digitalWrite(BUZZ_PIN, HIGH);
            } else {
              buzzerOn = false;
              digitalWrite(BUZZ_PIN, LOW);
            }
          }
          sendResponse(id, true);

        } else if (strcmp(target, "sensor_read") == 0) {
          float temp = dht.readTemperature();
          float hum  = dht.readHumidity();

          StaticJsonDocument<320> resp;
          resp["id"]     = id;
          resp["status"] = "ok";
          JsonObject st  = resp.createNestedObject("state");
          buildState(st);
          if (!isnan(temp)) resp["temp"]     = temp;
          if (!isnan(hum))  resp["humidity"] = hum;
          serializeJson(resp, Serial);
          Serial.print('\n');

        } else if (strcmp(target, "status") == 0) {
          sendResponse(id, true);

        } else {
          sendError(id, "unknown_target");
        }
      }
    }
  }

  // 2. Non-blocking buzzer auto-off
  if (buzzerOn && (millis() - buzzStartMs >= BUZZ_DURATION_MS)) {
    buzzerOn = false;
    digitalWrite(BUZZ_PIN, LOW);
  }

  // 3. Periodic telemetry
  if (millis() - lastTelemetryMs >= TELEMETRY_INTERVAL) {
    lastTelemetryMs = millis();
    sendTelemetry();
  }
}

// ── Helpers ───────────────────────────────────

void buildState(JsonObject state) {
  state["light"] = lightOn;
  state["relay"] = relayOn;
  state["servo"] = servoPos;
  JsonArray rgb  = state.createNestedArray("rgb");
  rgb.add(rgbR);
  rgb.add(rgbG);
  rgb.add(rgbB);
  state["buzzer"] = buzzerOn;
}

void sendResponse(int id, bool ok) {
  StaticJsonDocument<256> doc;
  doc["id"]          = id;
  doc["status"]      = ok ? "ok" : "error";
  JsonObject state   = doc.createNestedObject("state");
  buildState(state);
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void sendError(int id, const char* msg) {
  StaticJsonDocument<96> doc;
  doc["id"]     = id;
  doc["status"] = "error";
  doc["msg"]    = msg;
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void applyRGBInt(long color) {
  rgbR = (color >> 16) & 0xFF;
  rgbG = (color >>  8) & 0xFF;
  rgbB =  color        & 0xFF;
}

void sendTelemetry() {
  float temp = dht.readTemperature();
  float hum  = dht.readHumidity();

  StaticJsonDocument<128> doc;
  JsonObject tel   = doc.createNestedObject("telemetry");
  if (!isnan(temp)) tel["temp"]     = temp;
  if (!isnan(hum))  tel["humidity"] = hum;
  tel["uptime_ms"] = (long)millis();
  serializeJson(doc, Serial);
  Serial.print('\n');
}
