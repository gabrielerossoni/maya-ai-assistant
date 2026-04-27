/*
 * JARVIS Arduino Controller
 * ─────────────────────────────────────────────
 * Riceve comandi via seriale (9600 baud) e controlla:
 *   - LED (pin 13)
 *   - Relè (pin 7)
 *   - Servo (pin 9)
 *
 * Comandi accettati:
 *   LIGHT_ON   → accende LED
 *   LIGHT_OFF  → spegne LED
 *   RELAY_ON   → attiva relè (luce vera)
 *   RELAY_OFF  → disattiva relè
 *   SERVO_OPEN → servo a 90°
 *   SERVO_CLOSE → servo a 0°
 *   STATUS     → invia stato corrente
 *
 * Risposta: "OK:<comando>" o "ERR:<motivo>"
 */

#include <Servo.h>

// ── Pin ──────────────────────────────────────
const int PIN_LED   = 13;
const int PIN_RELAY =  7;
const int PIN_SERVO =  9;

// ── Stato componenti ─────────────────────────
bool lightOn  = false;
bool relayOn  = false;
int  servoPos = 0;

Servo myServo;

// ── Setup ────────────────────────────────────
void setup() {
  Serial.begin(9600);
  pinMode(PIN_LED,   OUTPUT);
  pinMode(PIN_RELAY, OUTPUT);

  myServo.attach(PIN_SERVO);
  myServo.write(0);

  // Stato iniziale: tutto spento
  digitalWrite(PIN_LED,   LOW);
  digitalWrite(PIN_RELAY, LOW);

  Serial.println("JARVIS_READY");
}

// ── Loop principale ──────────────────────────
void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    command.toUpperCase();

    if (command.length() == 0) return;

    Serial.print("CMD:");
    Serial.println(command);

    // ── Switch comandi ──────────────────────

    if (command == "LIGHT_ON") {
      digitalWrite(PIN_LED, HIGH);
      lightOn = true;
      Serial.println("OK:LIGHT_ON");

    } else if (command == "LIGHT_OFF") {
      digitalWrite(PIN_LED, LOW);
      lightOn = false;
      Serial.println("OK:LIGHT_OFF");

    } else if (command == "RELAY_ON") {
      digitalWrite(PIN_RELAY, HIGH);
      relayOn = true;
      Serial.println("OK:RELAY_ON");

    } else if (command == "RELAY_OFF") {
      digitalWrite(PIN_RELAY, LOW);
      relayOn = false;
      Serial.println("OK:RELAY_OFF");

    } else if (command == "SERVO_OPEN") {
      myServo.write(90);
      servoPos = 90;
      Serial.println("OK:SERVO_OPEN");

    } else if (command == "SERVO_CLOSE") {
      myServo.write(0);
      servoPos = 0;
      Serial.println("OK:SERVO_CLOSE");

    } else if (command == "STATUS") {
      sendStatus();

    } else {
      Serial.print("ERR:UNKNOWN_CMD:");
      Serial.println(command);
    }
  }

  delay(10);
}

// ── Funzione stato ───────────────────────────
void sendStatus() {
  Serial.print("STATUS:");
  Serial.print("LIGHT=");
  Serial.print(lightOn ? "ON" : "OFF");
  Serial.print(",RELAY=");
  Serial.print(relayOn ? "ON" : "OFF");
  Serial.print(",SERVO=");
  Serial.println(servoPos);
}
