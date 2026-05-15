/*
 * JARVIS Arduino Controller — JSON Protocol
 * ─────────────────────────────────────────────
 * ArduinoJson 6.x | 115200 baud
 *
 * Pin map:
 *   LED      → 13  |  Relay  →  7
 *   Servo    →  9  |  DHT11  →  4
 *   RGB R    →  5  |  RGB G  →  6  |  RGB B → 3
 *   Buzzer   →  8
 *
 * Incoming  (one JSON line, \n-terminated):
 *   {"id":<int>,"cmd":"SET"|"GET","target":"light"|"relay"|"servo"|
 *    "rgb"|"buzzer"|"sensor_read","value":<int|obj>}
 *
 * Response:
 *   {"id":<int>,"status":"ok"|"error",
 *    "state":{"light":bool,"relay":bool,"servo":int,
 *             "rgb":[r,g,b],"buzzer":bool}}
 *
 * sensor_read also adds "temp" and "humidity" at the top level.
 * Parse failure → {"id":-1,"status":"error","msg":"parse_fail"}
 * Telemetry (every 5 s, unsolicited):
 *   {"telemetry":{"temp":float,"humidity":float,"uptime_ms":long}}
 */

#include <ArduinoJson.h>
#include <Servo.h>
#include <DHT.h>

// ── Pin definitions ───────────────────────────
const int PIN_LED   = 13;
const int PIN_RELAY =  7;
const int PIN_SERVO =  9;
const int PIN_R     =  5;
const int PIN_G     =  6;
const int PIN_B     =  3;
const int PIN_BUZZ  =  8;
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

  pinMode(PIN_LED,   OUTPUT);
  pinMode(PIN_RELAY, OUTPUT);
  pinMode(PIN_BUZZ,  OUTPUT);
  pinMode(PIN_R,     OUTPUT);
  pinMode(PIN_G,     OUTPUT);
  pinMode(PIN_B,     OUTPUT);

  digitalWrite(PIN_LED,   LOW);
  digitalWrite(PIN_RELAY, LOW);
  digitalWrite(PIN_BUZZ,  LOW);
  analogWrite(PIN_R, 0);
  analogWrite(PIN_G, 0);
  analogWrite(PIN_B, 0);

  myServo.attach(PIN_SERVO);
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
            digitalWrite(PIN_LED, lightOn ? HIGH : LOW);
          }
          sendResponse(id, true);

        } else if (strcmp(target, "relay") == 0) {
          if (isSET) {
            relayOn = doc["value"].as<int>() != 0;
            digitalWrite(PIN_RELAY, relayOn ? HIGH : LOW);
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
            analogWrite(PIN_R, rgbR);
            analogWrite(PIN_G, rgbG);
            analogWrite(PIN_B, rgbB);
          }
          sendResponse(id, true);

        } else if (strcmp(target, "buzzer") == 0) {
          if (isSET) {
            if (doc["value"].as<int>() != 0) {
              buzzerOn    = true;
              buzzStartMs = millis();
              digitalWrite(PIN_BUZZ, HIGH);
            } else {
              buzzerOn = false;
              digitalWrite(PIN_BUZZ, LOW);
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
    digitalWrite(PIN_BUZZ, LOW);
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
