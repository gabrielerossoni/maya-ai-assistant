/*
 * MAYA Arduino Controller — JSON Protocol + MQTT (Uno R4 WiFi)
 * ─────────────────────────────────────────────────────────────
 * ArduinoJson 6.x | WiFiS3 | PubSubClient | Adafruit NeoPixel
 * 115200 baud (Serial) | MQTT Topics: maya/rooms/<room>/{cmd,state,telemetry}
 *
 * Pin map:
 *   WS2812B DATA (NeoPixel) →  2  (Freenove 8-LED module, 3 zone: Soggiorno/Camera/Studio)
 *   Speaker 8Ω Gikfun 2W   →  3  (melodie & notifiche, sostituisce buzzer2)
 *   DHT11                   →  4
 *   Buzzer 1 (Alarm)        →  8
 *   Servo 1 (Porta)         →  9
 *   Servo 2 (Cancello)      → 10
 *   LED Indicator           → 13
 *
 * Response/State format:
 *   {"id":<int>,"status":"ok"|"error",
 *    "state":{"light":bool,"servo":int,"servo2":int,
 *             "rgb1":[r,g,b],"rgb2":[r,g,b],"rgb3":[r,g,b],
 *             "neo_effect":int,"buzzer":bool,"buzz2_playing":bool}}
 */

#include "secrets.h"
#include <Adafruit_NeoPixel.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <PubSubClient.h>
#include <Servo.h>
#include <WiFiS3.h>

// ── WiFi Credentials ──────────────────────────
const char *SSID = WIFI_HOTSPOT_SSID;      // Configura il tuo SSID
const char *WIFI_PASS = WIFI_HOTSPOT_PASS; // Configura la password
const char *MQTT_BROKER = "localhost";     // Broker locale (default)
const int MQTT_PORT = 1883;
const char *MQTT_ROOM = "studio"; // Stanza di default
char MQTT_CLIENT_ID[32];

// ── Pin definitions ───────────────────────────
const int NEOPIXEL_PIN = 2;
const int SPEAKER_PIN = 3;   // Speaker 8Ω 2W Gikfun (ex buzzer2)
const int DHT_PIN = 4;
const int BUZZ_PIN = 8;
const int SERVO_PIN = 9;
const int SERVO2_PIN = 10;
const int LED_PIN = 13;

#define DHT_TYPE DHT11
#define NEOPIXEL_COUNT 24 // 3 modules of 8 LEDs each

// ── NeoPixel State (24 LEDs, 3 logical zones of 8 LEDs each) ──────
// Zone 1: LEDs 0-7, Zone 2: LEDs 8-15, Zone 3: LEDs 16-23
uint8_t ledsR[NEOPIXEL_COUNT] = {0};
uint8_t ledsG[NEOPIXEL_COUNT] = {0};
uint8_t ledsB[NEOPIXEL_COUNT] = {0};
int neoEffect = 0; // 0=solid, 1=pulse, 2=rainbow, 3=alert

// ── State ─────────────────────────────────────
bool lightOn = false;
int servoPos = 0;
int servo2Pos = 0;
bool buzzerOn = false;

// ── Buzzer 2 Melodies State ───────────────────
const char *currentMelody = "";
int melodyNoteIndex = -1;
unsigned long noteStartMs = 0;
int noteDuration = 0;

// ── Timing ────────────────────────────────────
unsigned long buzzStartMs = 0;
unsigned long lastTelemetryMs = 0;
unsigned long lastMqttConnectAttempt = 0;
unsigned long lastServo1AttachMs = 0;
unsigned long lastServo2AttachMs = 0;

const unsigned long BUZZ_DURATION_MS = 200;
const unsigned long TELEMETRY_INTERVAL = 5000;
const unsigned long MQTT_CONNECT_INTERVAL = 10000;
const unsigned long SERVO_DETACH_DELAY = 1000;

// ── MQTT & WiFi ───────────────────────────────
WiFiClient espClient;
PubSubClient mqttClient(espClient);

// ── Objects ────────────────────────────────────
Servo myServo;
Servo myServo2;
bool servo1Attached = false;
bool servo2Attached = false;
DHT dht(DHT_PIN, DHT_TYPE);
Adafruit_NeoPixel strip(NEOPIXEL_COUNT, NEOPIXEL_PIN, NEO_GRB + NEO_KHZ800);

// ── Prototypes ────────────────────────────────
void buildState(JsonObject state);
void sendResponse(int id, bool ok);
void sendError(int id, const char *msg);
void sendTelemetry();
void setupWiFi();
void connectMQTT();
void mqttCallback(char *topic, byte *payload, unsigned int length);
void publishState();
void handleMqttCommand(JsonDocument &cmd);
void handleSerialCommand(JsonDocument &doc);
void applyCommand(int id, bool isSET, const char *target, JsonDocument &doc);
void applyRGBInt(uint8_t &r, uint8_t &g, uint8_t &b, long color);
void startMelody(const char *name);
void updateMelody();
void updateNeoPixels();

// ── Setup ─────────────────────────────────────
void setup() {
  Serial.begin(115200);

  pinMode(LED_PIN, OUTPUT);
  pinMode(BUZZ_PIN, OUTPUT);
  pinMode(SPEAKER_PIN, OUTPUT);

  digitalWrite(LED_PIN, LOW);
  digitalWrite(BUZZ_PIN, LOW);

  // Initial servo position and detach
  myServo.attach(SERVO_PIN);
  myServo.write(0);
  myServo2.attach(SERVO2_PIN);
  myServo2.write(0);
  delay(500);
  myServo.detach();
  myServo2.detach();

  dht.begin();

  // NeoPixel initialization
  strip.begin();
  strip.show(); // Initialize all pixels to 'off'

  // Generate unique MQTT client ID
  snprintf(MQTT_CLIENT_ID, sizeof(MQTT_CLIENT_ID), "maya_arduino_%lX",
           micros());

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

  // 3. Async Melody Player & NeoPixel animator
  updateMelody();
  updateNeoPixels();

  // 4. Non-blocking buzzer 1 auto-off
  if (buzzerOn && (millis() - buzzStartMs >= BUZZ_DURATION_MS)) {
    buzzerOn = false;
    digitalWrite(BUZZ_PIN, LOW);
  }

  // 5. Periodic telemetry (MQTT + Serial)
  if (millis() - lastTelemetryMs >= TELEMETRY_INTERVAL) {
    lastTelemetryMs = millis();
    sendTelemetry();
    if (WiFi.status() == WL_CONNECTED && mqttClient.connected()) {
      publishTelemetry();
    }
  }

  // 6. Servo auto-detach logic
  if (servo1Attached && (millis() - lastServo1AttachMs >= SERVO_DETACH_DELAY)) {
    myServo.detach();
    servo1Attached = false;
  }
  if (servo2Attached && (millis() - lastServo2AttachMs >= SERVO_DETACH_DELAY)) {
    myServo2.detach();
    servo2Attached = false;
  }
}

// ── WiFi Setup ────────────────────────────────
void setupWiFi() {
  if (!ENABLE_WIFI) {
    return; // WiFi disabilitato
  }

  if (WiFi.status() == WL_CONNECTED)
    return; // Already connected

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
  if (WiFi.status() != WL_CONNECTED)
    return;

  if (mqttClient.connect(MQTT_CLIENT_ID)) {
    Serial.print("[MQTT] Connesso a ");
    Serial.println(MQTT_BROKER);

    // Subscribe a comando
    char subTopic[64];
    snprintf(subTopic, sizeof(subTopic), "maya/rooms/%s/cmd", MQTT_ROOM);
    mqttClient.subscribe(subTopic, 1); // QoS 1

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
void mqttCallback(char *topic, byte *payload, unsigned int length) {
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
void handleMqttCommand(JsonDocument &cmd) {
  int id = cmd["id"] | -1;
  const char *cmdOp = cmd["cmd"] | "";
  const char *target = cmd["target"] | "";

  bool isSET = (strcmp(cmdOp, "SET") == 0);
  bool isGET = (strcmp(cmdOp, "GET") == 0);

  if (!isSET && !isGET) {
    sendError(id, "bad_cmd");
    return;
  }

  applyCommand(id, isSET, target, cmd);
  publishState();
}

// ── Handle Serial Command ──────────────────────
void handleSerialCommand(JsonDocument &doc) {
  int id = doc["id"] | -1;
  const char *cmd = doc["cmd"] | "";
  const char *target = doc["target"] | "";

  bool isSET = (strcmp(cmd, "SET") == 0);
  bool isGET = (strcmp(cmd, "GET") == 0);

  if (!isSET && !isGET) {
    sendError(id, "bad_cmd");
    return;
  }

  applyCommand(id, isSET, target, doc);
}

// ── Apply Command (shared logic) ───────────────
void applyCommand(int id, bool isSET, const char *target, JsonDocument &doc) {
  if (strcmp(target, "light") == 0) {
    if (isSET) {
      lightOn = doc["value"].as<int>() != 0;
      digitalWrite(LED_PIN, lightOn ? HIGH : LOW);
    }
    sendResponse(id, true);

  } else if (strcmp(target, "servo") == 0) {
    if (isSET) {
      servoPos = constrain(doc["value"].as<int>(), 0, 180);
      myServo.attach(SERVO_PIN);
      myServo.write(servoPos);
      lastServo1AttachMs = millis();
      servo1Attached = true;
    }
    sendResponse(id, true);

  } else if (strcmp(target, "servo2") == 0) {
    if (isSET) {
      servo2Pos = constrain(doc["value"].as<int>(), 0, 180);
      myServo2.attach(SERVO2_PIN);
      myServo2.write(servo2Pos);
      lastServo2AttachMs = millis();
      servo2Attached = true;
    }
    sendResponse(id, true);

  } else if (strcmp(target, "rgb1") == 0) {
    if (isSET) {
      uint8_t r, g, b;
      JsonVariant val = doc["value"];
      if (val.is<JsonObject>()) {
        r = val["r"] | 0; g = val["g"] | 0; b = val["b"] | 0;
      } else {
        applyRGBInt(r, g, b, val.as<long>());
      }
      for (int i = 0; i < 8; i++) { ledsR[i] = r; ledsG[i] = g; ledsB[i] = b; }
      neoEffect = doc["effect"] | 0;
    }
    sendResponse(id, true);

  } else if (strcmp(target, "rgb2") == 0) {
    if (isSET) {
      uint8_t r, g, b;
      JsonVariant val = doc["value"];
      if (val.is<JsonObject>()) {
        r = val["r"] | 0; g = val["g"] | 0; b = val["b"] | 0;
      } else {
        applyRGBInt(r, g, b, val.as<long>());
      }
      for (int i = 8; i < 16; i++) { ledsR[i] = r; ledsG[i] = g; ledsB[i] = b; }
      neoEffect = doc["effect"] | 0;
    }
    sendResponse(id, true);

  } else if (strcmp(target, "rgb3") == 0) {
    if (isSET) {
      uint8_t r, g, b;
      JsonVariant val = doc["value"];
      if (val.is<JsonObject>()) {
        r = val["r"] | 0; g = val["g"] | 0; b = val["b"] | 0;
      } else {
        applyRGBInt(r, g, b, val.as<long>());
      }
      for (int i = 16; i < 24; i++) { ledsR[i] = r; ledsG[i] = g; ledsB[i] = b; }
      neoEffect = doc["effect"] | 0;
    }
    sendResponse(id, true);

  } else if (strncmp(target, "rgb", 3) == 0 && strlen(target) > 3) {
    // Individual LED control (up to 24)
    int idx = atoi(target + 3) - 1;
    if (idx >= 0 && idx < NEOPIXEL_COUNT) {
      if (isSET) {
        uint8_t r, g, b;
        JsonVariant val = doc["value"];
        if (val.is<JsonObject>()) {
          r = val["r"] | 0; g = val["g"] | 0; b = val["b"] | 0;
        } else {
          applyRGBInt(r, g, b, val.as<long>());
        }
        ledsR[idx] = r; ledsG[idx] = g; ledsB[idx] = b;
        neoEffect = doc["effect"] | 0;
      }
    }
    sendResponse(id, true);

  } else if (strcmp(target, "rgb") == 0 || strcmp(target, "neopixel") == 0) {
    // Shortcut: set all 24 LEDs to same color
    if (isSET) {
      JsonVariant val = doc["value"];
      uint8_t r, g, b;
      if (val.is<JsonObject>()) {
        r = val["r"] | 0; g = val["g"] | 0; b = val["b"] | 0;
      } else {
        long c = val.as<long>();
        r = (c >> 16) & 0xFF; g = (c >> 8) & 0xFF; b = c & 0xFF;
      }
      for (int i = 0; i < NEOPIXEL_COUNT; i++) {
        ledsR[i] = r; ledsG[i] = g; ledsB[i] = b;
      }
      neoEffect = doc["effect"] | 0;
    }
    sendResponse(id, true);

  } else if (strcmp(target, "buzzer") == 0) {
    if (isSET) {
      if (doc["value"].as<int>() != 0) {
        buzzerOn = true;
        buzzStartMs = millis();
        digitalWrite(BUZZ_PIN, HIGH);
      } else {
        buzzerOn = false;
        digitalWrite(BUZZ_PIN, LOW);
      }
    }
    sendResponse(id, true);

  } else if (strcmp(target, "buzzer2") == 0) {
    if (isSET) {
      const char *melodyName = doc["melody"] | "beep";
      startMelody(melodyName);
    }
    sendResponse(id, true);

  } else if (strcmp(target, "sensor_read") == 0) {
    float temp = dht.readTemperature();
    float hum = dht.readHumidity();

    StaticJsonDocument<384> resp;
    resp["id"] = id;
    resp["status"] = "ok";
    JsonObject st = resp.createNestedObject("state");
    buildState(st);
    if (!isnan(temp))
      resp["temp"] = temp;
    if (!isnan(hum))
      resp["humidity"] = hum;

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
  state["servo"] = servoPos;
  state["servo2"] = servo2Pos;
  JsonArray r1 = state.createNestedArray("rgb1");
  r1.add(ledsR[0]); r1.add(ledsG[0]); r1.add(ledsB[0]);
  JsonArray r2 = state.createNestedArray("rgb2");
  r2.add(ledsR[8]); r2.add(ledsG[8]); r2.add(ledsB[8]);
  JsonArray r3 = state.createNestedArray("rgb3");
  r3.add(ledsR[16]); r3.add(ledsG[16]); r3.add(ledsB[16]);
  state["neo_effect"] = neoEffect;
  state["buzzer"] = buzzerOn;
  state["buzz2_playing"] = (melodyNoteIndex >= 0);
}

void sendResponse(int id, bool ok) {
  StaticJsonDocument<384> doc;
  doc["id"] = id;
  doc["status"] = ok ? "ok" : "error";
  JsonObject state = doc.createNestedObject("state");
  buildState(state);
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void sendError(int id, const char *msg) {
  StaticJsonDocument<96> doc;
  doc["id"] = id;
  doc["status"] = "error";
  doc["msg"] = msg;
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void applyRGBInt(uint8_t &r, uint8_t &g, uint8_t &b, long color) {
  r = (color >> 16) & 0xFF;
  g = (color >> 8) & 0xFF;
  b = color & 0xFF;
}

void sendTelemetry() {
  float temp = dht.readTemperature();
  float hum = dht.readHumidity();

  StaticJsonDocument<256> doc;
  JsonObject tel = doc.createNestedObject("telemetry");
  if (!isnan(temp))
    tel["temp"] = temp;
  if (!isnan(hum))
    tel["humidity"] = hum;
  tel["uptime_ms"] = (long)millis();

  serializeJson(doc, Serial);
  Serial.print('\n');
}

void publishState() {
  if (!mqttClient.connected())
    return;

  StaticJsonDocument<384> doc;
  JsonObject state = doc.createNestedObject("state");
  buildState(state);

  char topic[64];
  snprintf(topic, sizeof(topic), "maya/rooms/%s/state", MQTT_ROOM);

  String payload;
  serializeJson(doc, payload);
  mqttClient.publish(topic, (const uint8_t *)payload.c_str(), payload.length(),
                     false);
}

void publishTelemetry() {
  if (!mqttClient.connected())
    return;

  float temp = dht.readTemperature();
  float hum = dht.readHumidity();

  StaticJsonDocument<256> doc;
  JsonObject tel = doc.createNestedObject("telemetry");
  if (!isnan(temp))
    tel["temp"] = temp;
  if (!isnan(hum))
    tel["humidity"] = hum;
  tel["uptime_ms"] = (long)millis();

  char topic[64];
  snprintf(topic, sizeof(topic), "maya/rooms/%s/telemetry", MQTT_ROOM);

  String payload;
  serializeJson(doc, payload);
  mqttClient.publish(topic, (const uint8_t *)payload.c_str(), payload.length(),
                     false);
}

// ── Melody functions ───────────────────────────
void startMelody(const char *name) {
  currentMelody = name;
  melodyNoteIndex = 0;
  noteStartMs = 0;
  noteDuration = 0;
}

void updateMelody() {
  if (melodyNoteIndex < 0)
    return;

  unsigned long now = millis();
  if (now - noteStartMs < noteDuration)
    return;

  noTone(SPEAKER_PIN);

  // Load next note in melody
  // Melodie ottimizzate per speaker Gikfun 8Ω 2W (range 200Hz–4kHz)
  if (strcmp(currentMelody, "beep") == 0) {
    int freqs[] = {1800};
    int durs[] = {120};
    int size = 1;
    if (melodyNoteIndex < size) {
      tone(SPEAKER_PIN, freqs[melodyNoteIndex]);
      noteDuration = durs[melodyNoteIndex];
      noteStartMs = now;
      melodyNoteIndex++;
    } else {
      melodyNoteIndex = -1;
    }
  } else if (strcmp(currentMelody, "alarm") == 0) {
    int freqs[] = {800, 1200, 800, 1200, 800, 1200};
    int durs[] = {200, 200, 200, 200, 200, 200};
    int size = 6;
    if (melodyNoteIndex < size) {
      tone(SPEAKER_PIN, freqs[melodyNoteIndex]);
      noteDuration = durs[melodyNoteIndex];
      noteStartMs = now;
      melodyNoteIndex++;
    } else {
      melodyNoteIndex = -1;
    }
  } else if (strcmp(currentMelody, "startup") == 0) {
    int freqs[] = {523, 659, 784, 1047}; // C5, E5, G5, C6
    int durs[] = {100, 100, 100, 200};
    int size = 4;
    if (melodyNoteIndex < size) {
      tone(SPEAKER_PIN, freqs[melodyNoteIndex]);
      noteDuration = durs[melodyNoteIndex];
      noteStartMs = now;
      melodyNoteIndex++;
    } else {
      melodyNoteIndex = -1;
    }
  } else if (strcmp(currentMelody, "ok") == 0) {
    int freqs[] = {660, 880}; // E5, A5
    int durs[] = {100, 150};
    int size = 2;
    if (melodyNoteIndex < size) {
      tone(SPEAKER_PIN, freqs[melodyNoteIndex]);
      noteDuration = durs[melodyNoteIndex];
      noteStartMs = now;
      melodyNoteIndex++;
    } else {
      melodyNoteIndex = -1;
    }
  } else if (strcmp(currentMelody, "notify") == 0) {
    // Notifica dolce — 2 note morbide (speaker 8Ω)
    int freqs[] = {880, 1109};  // A5, C#6
    int durs[] = {120, 180};
    int size = 2;
    if (melodyNoteIndex < size) {
      tone(SPEAKER_PIN, freqs[melodyNoteIndex]);
      noteDuration = durs[melodyNoteIndex];
      noteStartMs = now;
      melodyNoteIndex++;
    } else {
      melodyNoteIndex = -1;
    }
  } else if (strcmp(currentMelody, "error") == 0) {
    // Errore — tono discendente
    int freqs[] = {880, 440, 220}; // A5, A4, A3
    int durs[] = {150, 150, 300};
    int size = 3;
    if (melodyNoteIndex < size) {
      tone(SPEAKER_PIN, freqs[melodyNoteIndex]);
      noteDuration = durs[melodyNoteIndex];
      noteStartMs = now;
      melodyNoteIndex++;
    } else {
      melodyNoteIndex = -1;
    }
  } else if (strcmp(currentMelody, "welcome") == 0) {
    // Benvenuto — melodia calda e piacevole (sfrutta qualità speaker)
    int freqs[] = {523, 659, 784, 880, 1047, 1319}; // C5 E5 G5 A5 C6 E6
    int durs[] = {120, 120, 120, 120, 150, 250};
    int size = 6;
    if (melodyNoteIndex < size) {
      tone(SPEAKER_PIN, freqs[melodyNoteIndex]);
      noteDuration = durs[melodyNoteIndex];
      noteStartMs = now;
      melodyNoteIndex++;
    } else {
      melodyNoteIndex = -1;
    }
  } else {
    melodyNoteIndex = -1;
  }
}

// ── Non-blocking NeoPixel Effects ─────────────
void updateNeoPixels() {
  static unsigned long lastUpdate = 0;
  static int pulseDir = 1;
  static int pulseVal = 50;
  static uint8_t rainbowHue = 0;
  static bool alertOn = false;

  unsigned long now = millis();
  if (now - lastUpdate < 30)
    return; // ~33 FPS
  lastUpdate = now;

  if (neoEffect == 0) { // solid — use individual LED colors
    for (int i = 0; i < NEOPIXEL_COUNT; i++) {
      strip.setPixelColor(i, strip.Color(ledsR[i], ledsG[i], ledsB[i]));
    }
    strip.show();
  } else if (neoEffect == 1) { // pulse
    pulseVal += pulseDir * 5;
    if (pulseVal >= 255) { pulseVal = 255; pulseDir = -1; }
    if (pulseVal <= 30)  { pulseVal = 30;  pulseDir = 1;  }

    for (int i = 0; i < NEOPIXEL_COUNT; i++) {
      strip.setPixelColor(i, strip.Color((ledsR[i] * pulseVal) / 255, (ledsG[i] * pulseVal) / 255, (ledsB[i] * pulseVal) / 255));
    }
    strip.show();
  } else if (neoEffect == 2) { // rainbow — all LEDs
    rainbowHue += 1;
    for (int i = 0; i < NEOPIXEL_COUNT; i++) {
      uint8_t pixelHue = rainbowHue + (i * 256 / NEOPIXEL_COUNT);
      strip.setPixelColor(i, strip.gamma32(strip.ColorHSV(pixelHue * 256)));
    }
    strip.show();
  } else if (neoEffect == 3) { // alert — flash red on all LEDs
    static unsigned long lastFlash = 0;
    if (now - lastFlash >= 250) {
      lastFlash = now;
      alertOn = !alertOn;
    }
    uint32_t c = alertOn ? strip.Color(255, 0, 0) : 0;
    for (int i = 0; i < NEOPIXEL_COUNT; i++) {
      strip.setPixelColor(i, c);
    }
    strip.show();
  }
}
