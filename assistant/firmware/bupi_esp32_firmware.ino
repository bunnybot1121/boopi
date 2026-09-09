/*
 ===============================================================================
 BUPI ESP32 AUTONOMOUS ROBOT PLATFORM: COMPLETE MASTER FIRMWARE
 ===============================================================================
 Target Hardware: ESP32 Dev Module (ESP32-D0WD-V3)
 Actuators:       TB6612FNG Dual H-Bridge Driver + 2x N20 DC Gear Motors
 Sensors:         HC-SR04 Ultrasonic, PIR Motion Sensor, MPU6050 6-Axis IMU
 Features:        6-Axis IMU Engine, Gyro-Closed-Loop Yaw Turns, Reflex Barrier,
                  Dual-Channel (USB Serial 115200 + Wi-Fi WebSockets)

 PINOUT (Verified User Hardware):
   - Motor A (Left) : PWMA = 25, AIN1 = 26, AIN2 = 27
   - Motor B (Right): PWMB = 33, BIN1 = 14, BIN2 = 12
   - TB6612 Standby : STBY = 13 (Driven HIGH to enable driver)
   - HC-SR04 Trig   : TRIG = 5
   - HC-SR04 Echo   : ECHO = 18
   - PIR Sensor     : PIR  = 34 (with 19 fallback)
   - MPU6050 I2C    : SDA  = 21, SCL  = 22 (Address 0x68)
 ===============================================================================
*/

#include <WiFi.h>
#include <WebSocketsClient.h>
#include <Wire.h>
#include <math.h>

// ---------------- NETWORK CONFIGURATION ----------------
const char* ssid              = "CHINTU 4312";
const char* password          = "j016,48R";
const char* websocket_server  = "192.168.137.1";
const uint16_t websocket_port = 8767;

// ---------------- PIN DEFINITIONS ----------------
// Motor A (Left)
#define PIN_PWMA  25
#define PIN_AIN1  26
#define PIN_AIN2  27

// Motor B (Right)
#define PIN_PWMB  33
#define PIN_BIN1  14
#define PIN_BIN2  12

// TB6612 Standby
#define PIN_STBY  13

// Sensors
#define PIN_TRIG     5
#define PIN_ECHO     18
#define PIN_PIR      34
#define PIN_PIR_ALT  19

#define PIN_SDA      21
#define PIN_SCL      22
#define MPU_ADDR     0x68

// ---------------- SAFETY THRESHOLDS ----------------
const float CRITICAL_OBSTACLE_CM = 10.0; // Hard cutoff for forward drive
const float CRITICAL_TILT_DEG    = 45.0; // Rollover flip cutoff

// ---------------- GLOBAL STATE ----------------
WebSocketsClient webSocket;
bool wifiConnected = false;

unsigned long lastSensorTick  = 0;
unsigned long lastHeartbeat   = 0;
unsigned long motorEndTime    = 0;
unsigned long lastImuTime     = 0;
bool motorActive              = false;
String currentMovement        = "STOP";

float distanceCm       = 200.0;
float distanceFilter[3] = {200.0, 200.0, 200.0};
int   distanceIdx      = 0;
int   pirMotion        = 0;

// MPU6050 6-Axis Kinematics
float ax_g = 0.0, ay_g = 0.0, az_g = 1.0;
float gx_dps = 0.0, gy_dps = 0.0, gz_dps = 0.0;
float pitchDeg = 0.0, rollDeg = 0.0, headingDeg = 0.0;
float gz_bias = 0.0;
bool  obstacleCritical = false;

// Closed-loop angular turn state
bool targetTurnActive = false;
float targetHeadingDeg = 0.0;
int turnDirection = 0; // +1 = Right, -1 = Left
unsigned long turnTimeout = 0;

String serialRxBuffer = "";

// Forward Declarations
void stopMotors();
void forward(int speed = 255);
void backward(int speed = 255);
void left(int speed = 255);
void right(int speed = 255);
void executeMotorAction(const char* action, int speed, int durationMs);
void startTurnDegrees(float deltaDegrees, int speed = 255);
void updateClosedLoopTurn();

// ---------------- MOTOR CONTROLLER ----------------
void initMotors() {
  pinMode(PIN_AIN1, OUTPUT);
  pinMode(PIN_AIN2, OUTPUT);
  pinMode(PIN_PWMA, OUTPUT);

  pinMode(PIN_BIN1, OUTPUT);
  pinMode(PIN_BIN2, OUTPUT);
  pinMode(PIN_PWMB, OUTPUT);

  pinMode(PIN_STBY, OUTPUT);

  // Enable TB6612 driver on Pin 13
  digitalWrite(PIN_STBY, HIGH);

  // Direct 100% full battery voltage
  digitalWrite(PIN_PWMA, HIGH);
  digitalWrite(PIN_PWMB, HIGH);

  stopMotors();
}

void applyMotorPwm(int leftSpeed, int rightSpeed) {
  // Direct digital HIGH gives 100% full battery voltage (no PWM attenuation/stall)
  if (leftSpeed > 0) {
    digitalWrite(PIN_PWMA, HIGH);
  } else {
    digitalWrite(PIN_PWMA, LOW);
  }

  if (rightSpeed > 0) {
    digitalWrite(PIN_PWMB, HIGH);
  } else {
    digitalWrite(PIN_PWMB, LOW);
  }
}

void forward(int speed) {
  digitalWrite(PIN_STBY, HIGH);

  digitalWrite(PIN_AIN1, HIGH);
  digitalWrite(PIN_AIN2, LOW);

  digitalWrite(PIN_BIN1, HIGH);
  digitalWrite(PIN_BIN2, LOW);

  applyMotorPwm(speed, speed);
  motorActive = true;
  currentMovement = "FORWARD";
}

void backward(int speed) {
  digitalWrite(PIN_STBY, HIGH);

  digitalWrite(PIN_AIN1, LOW);
  digitalWrite(PIN_AIN2, HIGH);

  digitalWrite(PIN_BIN1, LOW);
  digitalWrite(PIN_BIN2, HIGH);

  applyMotorPwm(speed, speed);
  motorActive = true;
  currentMovement = "BACKWARD";
}

void left(int speed) {
  digitalWrite(PIN_STBY, HIGH);

  // Left motor backward, Right motor forward
  digitalWrite(PIN_AIN1, LOW);
  digitalWrite(PIN_AIN2, HIGH);

  digitalWrite(PIN_BIN1, HIGH);
  digitalWrite(PIN_BIN2, LOW);

  applyMotorPwm(speed, speed);
  motorActive = true;
  currentMovement = "LEFT";
}

void right(int speed) {
  digitalWrite(PIN_STBY, HIGH);

  // Left motor forward, Right motor backward
  digitalWrite(PIN_AIN1, HIGH);
  digitalWrite(PIN_AIN2, LOW);

  digitalWrite(PIN_BIN1, LOW);
  digitalWrite(PIN_BIN2, HIGH);

  applyMotorPwm(speed, speed);
  motorActive = true;
  currentMovement = "RIGHT";
}

void stopMotors() {
  digitalWrite(PIN_PWMA, LOW);
  digitalWrite(PIN_PWMB, LOW);

  digitalWrite(PIN_AIN1, LOW);
  digitalWrite(PIN_AIN2, LOW);

  digitalWrite(PIN_BIN1, LOW);
  digitalWrite(PIN_BIN2, LOW);

  motorActive = false;
  targetTurnActive = false;
  currentMovement = "STOP";
}

// ---------------- CLOSED-LOOP GYRO TURNING ----------------
void startTurnDegrees(float deltaDegrees, int speed) {
  float startHeading = headingDeg;
  targetHeadingDeg = fmod(startHeading + deltaDegrees + 360.0, 360.0);

  if (deltaDegrees >= 0) {
    turnDirection = 1; // Turn Right
    right(speed);
  } else {
    turnDirection = -1; // Turn Left
    left(speed);
  }

  targetTurnActive = true;
  turnTimeout = millis() + (unsigned long)(fabs(deltaDegrees) * 35.0) + 1500;
  Serial.printf("[GYRO TURN] Start: %.1f° -> Target: %.1f° (delta: %.1f°)\n", startHeading, targetHeadingDeg, deltaDegrees);
}

void updateClosedLoopTurn() {
  if (!targetTurnActive) return;

  // Smallest signed angular difference to target
  float diff = targetHeadingDeg - headingDeg;
  while (diff < -180.0) diff += 360.0;
  while (diff > 180.0) diff -= 360.0;

  // Stop when aligned within 3 degrees or timed out
  if ((turnDirection == 1 && diff <= 3.0 && diff >= -15.0) ||
      (turnDirection == -1 && diff >= -3.0 && diff <= 15.0) ||
      millis() > turnTimeout) {
    stopMotors();
    targetTurnActive = false;
    Serial.printf("[GYRO TURN COMPLETE] Reached Heading: %.1f° (Target: %.1f°)\n", headingDeg, targetHeadingDeg);
  }
}

// ---------------- SENSORS ----------------
void calibrateMPU() {
  Serial.print("[MPU6050] Calibrating gyro bias (keep robot still for 1s)...");
  float sum_gz = 0.0;
  int samples = 0;
  for (int i = 0; i < 40; i++) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x47); // GYRO_ZOUT_H
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)MPU_ADDR, (size_t)2, true);
    if (Wire.available() >= 2) {
      int16_t raw_gz = Wire.read() << 8 | Wire.read();
      sum_gz += raw_gz / 131.0;
      samples++;
    }
    delay(20);
  }
  if (samples > 0) {
    gz_bias = sum_gz / samples;
  }
  Serial.printf(" Done! Bias: %.2f deg/s\n", gz_bias);
}

void initSensors() {
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  pinMode(PIN_PIR, INPUT);
  pinMode(PIN_PIR_ALT, INPUT);

  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000); // 400kHz Fast I2C

  // Wake up MPU6050
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);
  Wire.write(0);
  Wire.endTransmission(true);

  calibrateMPU();
  lastImuTime = millis();
}

float readUltrasonic() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  // 18ms timeout (~3.1m range, non-blocking 20Hz safety)
  long durationUs = pulseIn(PIN_ECHO, HIGH, 18000);
  if (durationUs == 0) return 400.0;

  float rawCm = durationUs * 0.0343 / 2.0;
  if (rawCm < 2.0) return 400.0; // Filter noise

  // 3-sample median filter
  distanceFilter[distanceIdx] = constrain(rawCm, 2.0, 400.0);
  distanceIdx = (distanceIdx + 1) % 3;

  float a = distanceFilter[0];
  float b = distanceFilter[1];
  float c = distanceFilter[2];
  float median = (a > b) ? ((b > c) ? b : ((a > c) ? c : a)) : ((a > c) ? a : ((b > c) ? c : b));
  return median;
}

void readMPU() {
  unsigned long now = millis();
  float dt = (now - lastImuTime) / 1000.0;
  if (dt <= 0.0) dt = 0.02;
  lastImuTime = now;

  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU_ADDR, (size_t)14, true);

  if (Wire.available() >= 14) {
    int16_t raw_ax = Wire.read() << 8 | Wire.read();
    int16_t raw_ay = Wire.read() << 8 | Wire.read();
    int16_t raw_az = Wire.read() << 8 | Wire.read();
    Wire.read(); Wire.read(); // Skip temp
    int16_t raw_gx = Wire.read() << 8 | Wire.read();
    int16_t raw_gy = Wire.read() << 8 | Wire.read();
    int16_t raw_gz = Wire.read() << 8 | Wire.read();

    ax_g = raw_ax / 16384.0;
    ay_g = raw_ay / 16384.0;
    az_g = raw_az / 16384.0;
    gx_dps = raw_gx / 131.0;
    gy_dps = raw_gy / 131.0;
    gz_dps = raw_gz / 131.0;

    pitchDeg = atan2(-ax_g, sqrt(ay_g * ay_g + az_g * az_g)) * 180.0 / M_PI;
    rollDeg  = atan2(ay_g, az_g) * 180.0 / M_PI;

    // Gyro yaw integration with bias compensation
    float corrected_gz = gz_dps - gz_bias;
    if (fabs(corrected_gz) > 0.4) {
      headingDeg = fmod(headingDeg + (corrected_gz * dt) + 360.0, 360.0);
    }

    // Dynamic collision shock detection (> 1.8g total acceleration)
    float totalAccel = sqrt(ax_g * ax_g + ay_g * ay_g + az_g * az_g);
    if (totalAccel > 2.0 && motorActive) {
      Serial.printf("{\"warning\":\"COLLISION_SHOCK\",\"g_force\":%.2f}\n", totalAccel);
    }
  }
}

// ---------------- TELEMETRY BUILDER ----------------
String buildTelemetryJson() {
  char telemBuf[320];
  snprintf(telemBuf, sizeof(telemBuf),
    "{\"type\":\"telemetry\",\"device\":\"BUPI_ESP32\",\"distance_cm\":%.1f,\"pir\":%d,\"pitch\":%.1f,\"roll\":%.1f,\"heading\":%.1f,\"ax\":%.2f,\"ay\":%.2f,\"az\":%.2f,\"gz\":%.1f,\"obstacle\":%s,\"moving\":%s}",
    distanceCm,
    pirMotion,
    pitchDeg,
    rollDeg,
    headingDeg,
    ax_g, ay_g, az_g,
    gz_dps - gz_bias,
    obstacleCritical ? "true" : "false",
    motorActive ? "true" : "false"
  );
  return String(telemBuf);
}

// ---------------- ACTION EXECUTOR ----------------
void executeMotorAction(const char* action, int speed, int durationMs) {
  int spd = constrain(speed, 0, 255);
  if (spd <= 0) spd = 255;

  String act = String(action);
  act.trim();
  act.toLowerCase();

  // True tilt compensation for inverted MPU6050 mounting (resting ~ -170°)
  float effectiveRoll = (fabs(rollDeg) > 90.0) ? (180.0 - fabs(rollDeg)) : fabs(rollDeg);
  float effectivePitch = fabs(pitchDeg);

  if (effectivePitch > CRITICAL_TILT_DEG || effectiveRoll > CRITICAL_TILT_DEG) {
    Serial.printf("{\"warning\":\"TILT_HAZARD_CUTOFF\",\"pitch\":%.1f,\"roll\":%.1f}\n", pitchDeg, rollDeg);
    stopMotors();
    return;
  }

  // Forward movement check
  if (act == "forward" || act == "move_forward" || act == "move forward" || act == "w" || act == "f") {
    // Only block forward if confirmed obstacle <= 10.0 cm
    if (distanceCm > 0.0 && distanceCm <= 10.0) {
      Serial.printf("{\"warning\":\"CRITICAL_OBSTACLE_SAFETY_CUTOFF\",\"distance_cm\":%.1f}\n", distanceCm);
      stopMotors();
      return;
    }
    Serial.printf("[MOTOR] FORWARD (spd: %d, dur: %d ms)\n", spd, durationMs);
    forward(spd);
  }
  // Reverse is NEVER blocked by forward obstacle
  else if (act == "backward" || act == "move_backward" || act == "move backward" || act == "reverse" || act == "back" || act == "s" || act == "b") {
    Serial.printf("[MOTOR] BACKWARD (spd: %d, dur: %d ms)\n", spd, durationMs);
    backward(spd);
  }
  // Turns are NEVER blocked by forward obstacle (allows evasion)
  else if (act == "left" || act == "turn_left" || act == "turn left" || act == "l" || act == "a") {
    Serial.printf("[MOTOR] LEFT (spd: %d, dur: %d ms)\n", spd, durationMs);
    left(spd);
  }
  else if (act == "right" || act == "turn_right" || act == "turn right" || act == "r" || act == "d") {
    Serial.printf("[MOTOR] RIGHT (spd: %d, dur: %d ms)\n", spd, durationMs);
    right(spd);
  }
  else {
    stopMotors();
    return;
  }

  motorEndTime = (durationMs > 0) ? (millis() + durationMs) : 0;
}

// ---------------- COMMAND PARSER ----------------
void processCommandString(String str) {
  str.trim();
  if (str.length() == 0) return;

  // Single-key manual commands
  if (str.equalsIgnoreCase("w") || str.equalsIgnoreCase("f")) { executeMotorAction("forward", 255, 1000); return; }
  if (str.equalsIgnoreCase("s") || str.equalsIgnoreCase("b")) { executeMotorAction("backward", 255, 1000); return; }
  if (str.equalsIgnoreCase("a") || str.equalsIgnoreCase("l")) { executeMotorAction("left", 255, 600); return; }
  if (str.equalsIgnoreCase("d") || str.equalsIgnoreCase("r")) { executeMotorAction("right", 255, 600); return; }
  if (str.equalsIgnoreCase("stop") || str.equalsIgnoreCase("x") || str == " ") { stopMotors(); return; }

  // Extract action from JSON (e.g. {"action":"MOVE_FORWARD", "speed":255, "duration_ms":1000})
  String action = "";
  int speed = 255;
  int duration = 0;
  float degrees = 0.0;

  int actIdx = str.indexOf("\"action\"");
  if (actIdx != -1) {
    int colon = str.indexOf(':', actIdx);
    int q1 = str.indexOf('"', colon);
    int q2 = str.indexOf('"', q1 + 1);
    if (q1 != -1 && q2 != -1) {
      action = str.substring(q1 + 1, q2);
    }
  } else {
    action = str;
  }

  int degIdx = str.indexOf("\"degrees\"");
  if (degIdx != -1) {
    int colon = str.indexOf(':', degIdx);
    degrees = str.substring(colon + 1).toFloat();
  }

  int spdIdx = str.indexOf("\"speed\"");
  if (spdIdx != -1) {
    int colon = str.indexOf(':', spdIdx);
    speed = str.substring(colon + 1).toInt();
    if (speed <= 0) speed = 255;
  }

  int durIdx = str.indexOf("\"duration_ms\"");
  if (durIdx != -1) {
    int colon = str.indexOf(':', durIdx);
    duration = str.substring(colon + 1).toInt();
  }

  // Handle closed-loop angular turn commands
  if (action.equalsIgnoreCase("turn_by") || action.equalsIgnoreCase("rotate_by") || degrees != 0.0) {
    startTurnDegrees(degrees, speed);
    return;
  }
  if (action.equalsIgnoreCase("turn_right_90")) {
    startTurnDegrees(90.0, speed);
    return;
  }
  if (action.equalsIgnoreCase("turn_left_90")) {
    startTurnDegrees(-90.0, speed);
    return;
  }
  if (action.equalsIgnoreCase("turn_around") || action.equalsIgnoreCase("u_turn")) {
    startTurnDegrees(180.0, speed);
    return;
  }

  if (action.length() > 0) {
    executeMotorAction(action.c_str(), speed, duration);
  }
}

// ---------------- WEBSOCKET EVENT HANDLER ----------------
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch(type) {
    case WStype_DISCONNECTED:
      Serial.println("[WS] Disconnected from Boopi Hub.");
      break;

    case WStype_CONNECTED:
      Serial.println("[WS] Connected to Boopi Hub (ws://192.168.0.106:8767)!");
      webSocket.sendTXT("{\"type\":\"announce\",\"device\":\"BUPI Mobile Platform\",\"capabilities\":[\"differential_drive\",\"PIR\",\"HC-SR04\",\"MPU6050_6AXIS\",\"GYRO_TURNS\"],\"status\":\"online\"}");
      break;

    case WStype_TEXT:
      processCommandString((char*)payload);
      break;

    default:
      break;
  }
}

// ---------------- SETUP ----------------
void setup() {
  Serial.begin(115200);
  delay(800);

  Serial.println("\n\n========================================");
  Serial.println("     🤖 BUPI AUTONOMOUS ROBOT PLATFORM   ");
  Serial.println("========================================");

  initMotors();
  initSensors();

  // Bootup Confirmation Test: Quick 250ms forward pulse to prove battery & motors are alive!
  Serial.println("[Diagnostics] Running 250ms motor wakeup test...");
  forward(255);
  delay(250);
  stopMotors();
  delay(200);

  // Connect Wi-Fi
  Serial.print("[WiFi] Connecting to '");
  Serial.print(ssid);
  Serial.print("'");
  WiFi.begin(ssid, password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 12) {
    delay(350);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    wifiConnected = true;
    Serial.println("\n[WiFi] Connected! IP: " + WiFi.localIP().toString());

    webSocket.begin(websocket_server, websocket_port, "/");
    webSocket.onEvent(webSocketEvent);
    webSocket.setReconnectInterval(3000);
    Serial.printf("[WS] Connecting to Boopi Hub at ws://%s:%d/\n", websocket_server, websocket_port);
  } else {
    wifiConnected = false;
    Serial.println("\n[WiFi] Operating in USB Serial standalone mode.");
  }

  Serial.println("========================================");
  Serial.println("   READY FOR NATURAL LANGUAGE MISSIONS  ");
  Serial.println("========================================\n");
}

// ---------------- MAIN NON-BLOCKING 20HZ LOOP ----------------
void loop() {
  if (wifiConnected) {
    webSocket.loop();
  }

  unsigned long now = millis();

  // 1. Process Serial Commands (USB Cable)
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (serialRxBuffer.length() > 0) {
        processCommandString(serialRxBuffer);
        serialRxBuffer = "";
      }
    } else {
      serialRxBuffer += c;
    }
  }

  // 2. 20 Hz Perception & Telemetry Cycle (every 50ms)
  if (now - lastSensorTick >= 50) {
    lastSensorTick = now;

    distanceCm = readUltrasonic();
    pirMotion  = digitalRead(PIN_PIR) || digitalRead(PIN_PIR_ALT);
    readMPU();

    // Check closed-loop angular gyro turn progress
    updateClosedLoopTurn();

    // Reflex Barrier Cutoff (Only if actively driving forward)
    obstacleCritical = (distanceCm <= CRITICAL_OBSTACLE_CM);
    if (obstacleCritical && motorActive && currentMovement == "FORWARD") {
      stopMotors();
      Serial.printf("{\"safety_event\":\"BARRIER_COLLISION_CUTOFF\",\"distance_cm\":%.1f}\n", distanceCm);
    }

    String telemetryStr = buildTelemetryJson();
    Serial.println(telemetryStr);

    if (wifiConnected && webSocket.isConnected()) {
      webSocket.sendTXT(telemetryStr);
    }
  }

  // 3. Timed Motor Duration Cutoff
  if (motorEndTime > 0 && now >= motorEndTime) {
    stopMotors();
    motorEndTime = 0;
  }

  // 4. Periodic Heartbeat (Every 5 Seconds)
  if (now - lastHeartbeat >= 5000) {
    lastHeartbeat = now;
    if (wifiConnected && webSocket.isConnected()) {
      webSocket.sendTXT("{\"type\":\"heartbeat\",\"device\":\"BUPI_ESP32\",\"status\":\"online\"}");
    }
  }
}
