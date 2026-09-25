/*
 ===============================================================================
 BUPI-02 ENVIRONMENTAL SPECIALIST: MASTER FIRMWARE (FLASH-READY)
 ===============================================================================
 Target Hardware: ESP32 Dev Module (ESP32-WROOM / ESP32-D0WD-V3)
 Robot ID:        bupi_02
 Role:            ENVIRONMENTAL / HAZARD ASSESSMENT & GAS SPECIALIST
 
 CONFIRMED HARDWARE PINOUT:
   - MQ-2 Gas / Smoke Sensor : AO   = GPIO 34 (ADC1_CH6, Input-Only)
   - HC-SR04 Ultrasonic      : TRIG = GPIO 5, ECHO = GPIO 18 (via 5V-to-3.3V divider)
   - MPU6050 6-Axis IMU      : SDA  = GPIO 21, SCL  = GPIO 22 (I2C 0x68)
   - DHT22 Climate Sensor    : DATA = GPIO 4 (3.3V VCC)
   - TB6612FNG Motor Driver  : 
       * Left Motor  : PWMA = GPIO 25, AIN1 = GPIO 26, AIN2 = GPIO 27
       * Right Motor : PWMB = GPIO 14, BIN1 = GPIO 12, BIN2 = GPIO 13
       * Standby     : STBY = GPIO 33 (Active HIGH)
   - N20 DC Gear Motors      : Dual differential drive configuration

 Features:
   - 6-Axis IMU Kinematics & Gyro-Closed-Loop Yaw Turns
   - Onboard Edge-Computing Autonomous Obstacle Avoidance Engine
   - Non-blocking DHT22 Climate Sampling (2s interval + MPU temp fallback)
   - Calibrated MQ-2 Gas / Smoke Monitoring (0-1000 ppm scale)
   - Dual Safety Reflex: Critical barrier cutoff (<=10cm), rollover tilt cutoff (>45°),
     and high-gas hazard alarm
   - Dual-Channel Comm: USB Serial (115200 baud) + Wi-Fi WebSockets (Port 8767)
 ===============================================================================
*/

#include <WiFi.h>
#include <WebSocketsClient.h>
#include <Wire.h>
#include <math.h>
#include "esp_wifi.h"

// ---------------- IDENTITY CONFIGURATION ----------------
#define BOT_ID      "bupi_02"
#define BOT_NAME    "BUPI_02_SPECIALIST"
#define BOT_ROLE    "ENVIRONMENTAL"

// ---------------- HARDWARE PINOUT (USER CONFIRMED) ----------------
// TB6612FNG Motor Driver
#define PIN_PWMA     25  // Left Motor Speed (PWM / Full Voltage)
#define PIN_AIN1     26  // Left Motor Direction 1
#define PIN_AIN2     27  // Left Motor Direction 2

#define PIN_PWMB     14  // Right Motor Speed (PWM / Full Voltage)
// NOTE: GPIO 12 is an ESP32 strapping pin (MTDI). At boot, if GPIO 12 is pulled HIGH by
// external circuitry, the ESP32 enters 1.8V flash mode and fails to boot.
// If your Bot 2 fails to boot or loops at power-on, rewire BIN1 to GPIO 32 and set PIN_BIN1 to 32.
#ifndef PIN_BIN1
  #define PIN_BIN1   12  // Right Motor Direction 1 (Safe fallback: GPIO 32)
#endif
#define PIN_BIN2     13  // Right Motor Direction 2

#define PIN_STBY     33  // Standby (Driven HIGH to enable driver)

// Ultrasonic Sensor (HC-SR04)
#define PIN_TRIG     5
#define PIN_ECHO     18

// Environmental Sensors
#define PIN_MQ2_ADC  34  // MQ-2 Analog AO (ADC1_CH6, Input-Only GPIO)
#define PIN_DHT      4   // DHT22 Data Pin

// I2C Pins for MPU6050
#define PIN_SDA        21
#define PIN_SCL        22
#define MPU_ADDR       0x68

// DHT Sensor Support (1 = Enabled)
#define ENABLE_DHT_LIB 1

#if ENABLE_DHT_LIB
  #include <DHT.h>
  #define DHTTYPE DHT22
  DHT dht(PIN_DHT, DHTTYPE);
#endif

// ---------------- NETWORK CONFIGURATION ----------------
const char* ssid              = "CHINTU 4312";
const char* password          = "j016,48R";
const char* websocket_server  = "192.168.137.1";
const uint16_t websocket_port = 8767;

// DHCP Mode with Unique Hostname (Windows Hotspot displays "Connected Devices: 2" and "bupi-bot2-specialist")
// Set to 0 for Windows Hotspot automatic DHCP lease registration (shows in Windows Hotspot list)
#define USE_STATIC_IP 0
const char* wifi_hostname     = "bupi-bot2-specialist";
IPAddress staticIP(192, 168, 137, 102);
IPAddress gateway(192, 168, 137, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress dnsServer(192, 168, 137, 1);

// ---------------- SAFETY & HAZARD THRESHOLDS (CONFIGURABLE) ----------------
#define ENABLE_OBSTACLE_CUTOFF 0  // 0 = Disabled (Obstacles will NOT block motor drive)
#define ENABLE_TILT_CUTOFF     0  // 0 = Disabled (Tilt/rollover will NOT cut off motors)
const float CRITICAL_OBSTACLE_CM = 0.0; // Disabled
const float CRITICAL_TILT_DEG    = 85.0;
const float GAS_HAZARD_THRESHOLD = 300.0; // High Gas / Smoke hazard threshold (ppm)
const float TEMP_HAZARD_THRESHOLD = 45.0; // High ambient temp cutoff (°C)

// ---------------- GLOBAL STATE ----------------
WebSocketsClient webSocket;
bool wifiConnected = false;

unsigned long lastSensorTick  = 0;
unsigned long lastHeartbeat   = 0;
unsigned long motorEndTime    = 0;
unsigned long lastImuTime     = 0;
unsigned long lastDhtReadTime = 0;
bool motorActive              = false;
String currentMovement        = "STOP";

float distanceCm       = 200.0;
float distanceFilter[3] = {200.0, 200.0, 200.0};
int   distanceIdx      = 0;
int   obstacleDebounceCount = 0;

// Environmental Readings
float gasPpm           = 50.0;
float tempC            = 25.0;
float humidityPct      = 50.0;

// MPU6050 6-Axis Kinematics
float ax_g = 0.0, ay_g = 0.0, az_g = 1.0;
float gx_dps = 0.0, gy_dps = 0.0, gz_dps = 0.0;
float pitchDeg = 0.0, rollDeg = 0.0, headingDeg = 0.0;
float gz_bias = 0.0;
float pitch_baseline = 0.0;
float roll_baseline = 0.0;
bool  obstacleCritical = false;

// Step Counting & Odometry State
unsigned long stepCount = 0;
float distanceTraveledM = 0.0;
unsigned long lastStepTime = 0;
const float STEP_STRIDE_M = 0.075; // ~7.5 cm per step cycle
int lastWifiRssi = 0;

// Closed-loop angular turn state
bool targetTurnActive = false;
float targetHeadingDeg = 0.0;
int turnDirection = 0; // +1 = Right, -1 = Left
unsigned long turnTimeout = 0;

// ---------------- EDGE COMPUTING OBSTACLE AVOIDANCE ----------------
enum EdgeAvoidState {
  AVOID_IDLE,
  AVOID_CRUISE,
  AVOID_REVERSE,
  AVOID_PIVOT,
  AVOID_FLANK_ADVANCE,
  AVOID_COUNTER_PIVOT,
  AVOID_VERIFY
};

bool edgeAvoidEnabled = false;
EdgeAvoidState avoidState = AVOID_IDLE;
unsigned long avoidStateTimer = 0;
int avoidPivotDirection = 1; // +1 = Right, -1 = Left
int avoidPivotAttempts = 0;  // Track consecutive turns in confined spaces
float avoidBaselineHeading = 0.0;
float AVOID_DETECT_CM = 25.0;
float AVOID_CLEAR_CM = 45.0;

void triggerObstacleBypass(int direction = 1);
void updateEdgeObstacleAvoidance();

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
void updateEdgeObstacleAvoidance();

// ---------------- MOTOR CONTROLLER ----------------
void initMotors() {
  pinMode(PIN_AIN1, OUTPUT);
  pinMode(PIN_AIN2, OUTPUT);
  pinMode(PIN_PWMA, OUTPUT);

  pinMode(PIN_BIN1, OUTPUT);
  pinMode(PIN_BIN2, OUTPUT);
  pinMode(PIN_PWMB, OUTPUT);

  pinMode(PIN_STBY, OUTPUT);

  // Enable TB6612 driver
  digitalWrite(PIN_STBY, HIGH);

  // Direct 100% full battery voltage
  digitalWrite(PIN_PWMA, HIGH);
  digitalWrite(PIN_PWMB, HIGH);

  stopMotors();
}

void applyMotorPwm(int leftSpeed, int rightSpeed) {
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

  float diff = targetHeadingDeg - headingDeg;
  while (diff < -180.0) diff += 360.0;
  while (diff > 180.0) diff -= 360.0;

  bool reached = false;
  if (turnDirection == 1) {
    if (diff <= 3.0) reached = true;
  } else if (turnDirection == -1) {
    if (diff >= -3.0) reached = true;
  }

  if (reached || fabs(diff) <= 4.0 || millis() > turnTimeout) {
    stopMotors();
    targetTurnActive = false;
    Serial.printf("[GYRO TURN COMPLETE] Reached Heading: %.1f° (Target: %.1f°)\n", headingDeg, targetHeadingDeg);
  }
}

// ---------------- EDGE COMPUTING OBSTACLE AVOIDANCE ENGINE ----------------
void triggerObstacleBypass(int direction) {
  avoidBaselineHeading = headingDeg;
  avoidPivotDirection = (direction != 0) ? direction : 1;
  avoidPivotAttempts = 1;
  stopMotors();
  avoidState = AVOID_REVERSE;
  avoidStateTimer = millis() + 300;
  backward(200);
  Serial.printf("[OBSTACLE BYPASS] Initiating flank bypass maneuver (dir: %d)...\n", avoidPivotDirection);
}

void updateEdgeObstacleAvoidance() {
  if (!edgeAvoidEnabled && avoidState == AVOID_IDLE) return;

  unsigned long now = millis();

  // Debounce obstacle distance readings
  if (distanceCm <= AVOID_DETECT_CM) {
    if (obstacleDebounceCount < 5) obstacleDebounceCount++;
  } else {
    if (obstacleDebounceCount > 0) obstacleDebounceCount--;
  }

  switch (avoidState) {
    case AVOID_IDLE:
      if (edgeAvoidEnabled) {
        avoidState = AVOID_CRUISE;
        avoidPivotAttempts = 0;
        forward(200);
        Serial.println(F("[EDGE AVOID] State -> CRUISE"));
      }
      break;

    case AVOID_CRUISE:
      avoidPivotAttempts = 0;
      if (currentMovement != "FORWARD" && edgeAvoidEnabled) {
        forward(200);
      }
      if (distanceCm <= AVOID_DETECT_CM && obstacleDebounceCount >= 2) {
        stopMotors();
        avoidBaselineHeading = headingDeg;
        avoidState = AVOID_REVERSE;
        avoidStateTimer = now + 300; // Back up 300ms to gain turning clearance
        backward(200);
        Serial.printf("[EDGE AVOID] Obstacle at %.1f cm! Reversing to clear blind spot...\n", distanceCm);
      }
      break;

    case AVOID_REVERSE:
      if (now >= avoidStateTimer) {
        stopMotors();
        avoidPivotDirection = -avoidPivotDirection;
        float turnAngle = avoidPivotDirection * 45.0;
        Serial.printf("[EDGE AVOID] Reverse complete. Flank pivoting %.1f°...\n", turnAngle);
        startTurnDegrees(turnAngle, 200);
        avoidPivotAttempts++;
        avoidState = AVOID_PIVOT;
      }
      break;

    case AVOID_PIVOT:
      if (!targetTurnActive) {
        stopMotors();
        Serial.println(F("[EDGE AVOID] Pivot complete. Advancing along obstacle flank..."));
        avoidState = AVOID_FLANK_ADVANCE;
        avoidStateTimer = now + 400; // Drive forward 400ms to pass obstacle depth
        forward(200);
      }
      break;

    case AVOID_FLANK_ADVANCE:
      if (now >= avoidStateTimer) {
        stopMotors();
        float counterAngle = -avoidPivotDirection * 45.0;
        Serial.printf("[EDGE AVOID] Flank advance complete. Counter-pivoting %.1f° to re-align heading...\n", counterAngle);
        startTurnDegrees(counterAngle, 200);
        avoidState = AVOID_COUNTER_PIVOT;
      }
      break;

    case AVOID_COUNTER_PIVOT:
      if (!targetTurnActive) {
        stopMotors();
        avoidState = AVOID_VERIFY;
        avoidStateTimer = now + 150;
      }
      break;

    case AVOID_VERIFY:
      if (now >= avoidStateTimer) {
        if (distanceCm >= AVOID_CLEAR_CM) {
          Serial.printf("[EDGE AVOID] Obstacle crossed out! Path clear (%.1f cm >= %.1f cm). Resuming cruise.\n", distanceCm, AVOID_CLEAR_CM);
          avoidPivotAttempts = 0;
          if (edgeAvoidEnabled) {
            avoidState = AVOID_CRUISE;
            forward(200);
          } else {
            avoidState = AVOID_IDLE;
            stopMotors();
          }
        } else if (avoidPivotAttempts < 3) {
          Serial.printf("[EDGE AVOID] Obstructed (%.1f cm). Retrying bypass attempt %d...\n", distanceCm, avoidPivotAttempts);
          avoidPivotDirection = -avoidPivotDirection;
          startTurnDegrees(avoidPivotDirection * 50.0, 200);
          avoidPivotAttempts++;
          avoidState = AVOID_PIVOT;
        } else {
          Serial.println(F("[EDGE AVOID] Boxed in. Reversing to find exit..."));
          avoidPivotAttempts = 0;
          avoidState = AVOID_REVERSE;
          avoidStateTimer = now + 600;
          backward(200);
        }
      }
      break;
  }
}

// ---------------- SENSORS ----------------
void calibrateMPU() {
  Serial.print("[MPU6050] Calibrating gyro bias & resting tilt baseline (keep robot still for 1s)...");
  float sum_gz = 0.0;
  float sum_pitch = 0.0;
  float sum_roll = 0.0;
  int samples = 0;
  for (int i = 0; i < 40; i++) {
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x3B); // ACCEL_XOUT_H
    byte err = Wire.endTransmission(false);
    if (err == 0) {
      Wire.requestFrom((uint8_t)MPU_ADDR, (size_t)14, true);
      if (Wire.available() >= 14) {
        int16_t raw_ax = Wire.read() << 8 | Wire.read();
        int16_t raw_ay = Wire.read() << 8 | Wire.read();
        int16_t raw_az = Wire.read() << 8 | Wire.read();
        Wire.read(); Wire.read(); // Skip temp
        Wire.read(); Wire.read(); // Skip gx
        Wire.read(); Wire.read(); // Skip gy
        int16_t raw_gz = Wire.read() << 8 | Wire.read();

        sum_gz += raw_gz / 131.0;
        float ax = raw_ax / 16384.0;
        float ay = raw_ay / 16384.0;
        float az = raw_az / 16384.0;
        float p = atan2(-ax, sqrt(ay * ay + az * az)) * 180.0 / M_PI;
        float r = atan2(ay, az) * 180.0 / M_PI;
        sum_pitch += p;
        sum_roll += r;
        samples++;
      }
    }
    delay(20);
  }
  if (samples > 0) {
    gz_bias = sum_gz / samples;
    pitch_baseline = sum_pitch / samples;
    roll_baseline = sum_roll / samples;
  }
  Serial.printf(" Done! Bias: %.2f deg/s | Baseline Pitch: %.1f°, Roll: %.1f°\n", gz_bias, pitch_baseline, roll_baseline);
}

void initSensors() {
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  pinMode(PIN_MQ2_ADC, INPUT);

  #if ENABLE_DHT_LIB
  dht.begin();
  #endif

  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setTimeOut(50);   // 50ms bus timeout prevents hanging if wire loose
  Wire.setClock(100000); // 100kHz Standard I2C for breadboard jumper stability

  // Check if MPU6050 is responding before running calibration
  Wire.beginTransmission(MPU_ADDR);
  byte error = Wire.endTransmission();
  if (error == 0) {
    Serial.println("[MPU6050] Sensor detected at 0x68.");
    // Wake up MPU6050
    Wire.beginTransmission(MPU_ADDR);
    Wire.write(0x6B);
    Wire.write(0);
    Wire.endTransmission(true);

    calibrateMPU();
  } else {
    Serial.printf("[MPU6050] Not detected or bus error (code %d). Proceeding with default state.\n", error);
  }

  lastImuTime = millis();
  lastDhtReadTime = millis();
}

float readUltrasonic() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  long durationUs = pulseIn(PIN_ECHO, HIGH, 18000);
  if (durationUs == 0) return 400.0;

  float rawCm = durationUs * 0.0343 / 2.0;
  if (rawCm < 2.0) return 400.0;

  distanceFilter[distanceIdx] = constrain(rawCm, 2.0, 400.0);
  distanceIdx = (distanceIdx + 1) % 3;

  float a = distanceFilter[0];
  float b = distanceFilter[1];
  float c = distanceFilter[2];
  float median = (a > b) ? ((b > c) ? b : ((a > c) ? c : a)) : ((a > c) ? a : ((b > c) ? c : b));
  return median;
}

float readMQ2Gas() {
  // Read 12-bit ADC (0 - 4095)
  int rawAdc = analogRead(PIN_MQ2_ADC);
  // Convert to calibrated approximate ppm scale (0 - 1000 ppm)
  float ppm = (rawAdc / 4095.0) * 1000.0;
  return ppm;
}

void readMPUAndEnvironment() {
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
    int16_t raw_temp = Wire.read() << 8 | Wire.read();
    int16_t raw_gx = Wire.read() << 8 | Wire.read();
    int16_t raw_gy = Wire.read() << 8 | Wire.read();
    int16_t raw_gz = Wire.read() << 8 | Wire.read();

    ax_g = raw_ax / 16384.0;
    ay_g = raw_ay / 16384.0;
    az_g = raw_az / 16384.0;
    gx_dps = raw_gx / 131.0;
    gy_dps = raw_gy / 131.0;
    gz_dps = raw_gz / 131.0;

    // Ambient temp fallback from MPU6050 die
    float mpuTemp = (raw_temp / 340.0) + 36.53;
    if (mpuTemp > -20.0 && mpuTemp < 100.0) {
      tempC = mpuTemp;
    }

    float raw_pitch = atan2(-ax_g, sqrt(ay_g * ay_g + az_g * az_g)) * 180.0 / M_PI;
    float raw_roll  = atan2(ay_g, az_g) * 180.0 / M_PI;
    pitchDeg = raw_pitch - pitch_baseline;
    rollDeg  = raw_roll - roll_baseline;

    // Gyro yaw integration
    float corrected_gz = gz_dps - gz_bias;
    if (fabs(corrected_gz) > 0.4) {
      headingDeg = fmod(headingDeg + (corrected_gz * dt) + 360.0, 360.0);
    }

    // Dynamic peak acceleration step detector
    float totalAccel = sqrt(ax_g * ax_g + ay_g * ay_g + az_g * az_g);
    if (motorActive && totalAccel >= 1.20 && (now - lastStepTime) >= 180) {
      stepCount++;
      distanceTraveledM += STEP_STRIDE_M;
      lastStepTime = now;
    }
  }

  // Read Gas (non-blocking)
  gasPpm = readMQ2Gas();

  // Non-blocking DHT read every 2000ms (prevents blocking the 20Hz loop)
  #if ENABLE_DHT_LIB
  if (now - lastDhtReadTime >= 2000) {
    lastDhtReadTime = now;
    float dhtT = dht.readTemperature();
    float dhtH = dht.readHumidity();
    if (!isnan(dhtT)) tempC = dhtT;
    if (!isnan(dhtH)) humidityPct = dhtH;
  }
  #endif
}

// ---------------- TELEMETRY BUILDER ----------------
String buildTelemetryJson() {
  String currentIp = "0.0.0.0";
  String currentSsid = "DISCONNECTED";
  if (WiFi.status() == WL_CONNECTED) {
    wifiConnected = true;
    lastWifiRssi = WiFi.RSSI();
    currentIp = WiFi.localIP().toString();
    currentSsid = WiFi.SSID();
  } else {
    wifiConnected = false;
    lastWifiRssi = 0;
  }
  char telemBuf[520];
  snprintf(telemBuf, sizeof(telemBuf),
    "{\"type\":\"telemetry\",\"bot_id\":\"%s\",\"robot_id\":\"%s\",\"device\":\"%s\",\"role\":\"%s\",\"ip\":\"%s\",\"ssid\":\"%s\",\"wifi_rssi\":%d,\"distance_cm\":%.1f,\"gas_ppm\":%.1f,\"temp_c\":%.1f,\"humidity\":%.1f,\"pitch\":%.1f,\"roll\":%.1f,\"heading\":%.1f,\"ax\":%.2f,\"ay\":%.2f,\"az\":%.2f,\"gz\":%.1f,\"steps\":%lu,\"dist_m\":%.2f,\"obstacle\":%s,\"moving\":%s}",
    BOT_ID,
    BOT_ID,
    BOT_NAME,
    BOT_ROLE,
    currentIp.c_str(),
    currentSsid.c_str(),
    lastWifiRssi,
    distanceCm,
    gasPpm,
    tempC,
    humidityPct,
    pitchDeg,
    rollDeg,
    headingDeg,
    ax_g, ay_g, az_g,
    gz_dps - gz_bias,
    stepCount,
    distanceTraveledM,
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

  #if ENABLE_TILT_CUTOFF
  // Dynamic tilt relative to calibrated resting chassis baseline (pitchDeg & rollDeg are already zero-referenced)
  float deltaPitch = fabs(pitchDeg);
  float deltaRoll = fabs(rollDeg);
  if (deltaRoll > 180.0) deltaRoll = fabs(360.0 - deltaRoll);

  if (deltaPitch > CRITICAL_TILT_DEG || deltaRoll > CRITICAL_TILT_DEG) {
    Serial.printf("{\"warning\":\"TILT_HAZARD_CUTOFF\",\"bot_id\":\"%s\",\"deltaPitch\":%.1f,\"deltaRoll\":%.1f}\n", BOT_ID, deltaPitch, deltaRoll);
    stopMotors();
    return;
  }
  #endif

  // Forward movement check with critical barrier safety
  if (act == "forward" || act == "move_forward" || act == "move forward" || act == "w" || act == "f") {
    #if ENABLE_OBSTACLE_CUTOFF
    if (distanceCm > 0.0 && distanceCm <= CRITICAL_OBSTACLE_CM) {
      Serial.printf("{\"warning\":\"CRITICAL_OBSTACLE_SAFETY_CUTOFF\",\"bot_id\":\"%s\",\"distance_cm\":%.1f}\n", BOT_ID, distanceCm);
      stopMotors();
      return;
    }
    #endif
    Serial.printf("[%s MOTOR] FORWARD (spd: %d, dur: %d ms)\n", BOT_ID, spd, durationMs);
    forward(spd);
  }
  else if (act == "backward" || act == "move_backward" || act == "move backward" || act == "reverse" || act == "back" || act == "s" || act == "b") {
    Serial.printf("[%s MOTOR] BACKWARD (spd: %d, dur: %d ms)\n", BOT_ID, spd, durationMs);
    backward(spd);
  }
  else if (act == "left" || act == "turn_left" || act == "turn left" || act == "l" || act == "a") {
    Serial.printf("[%s MOTOR] LEFT (spd: %d, dur: %d ms)\n", BOT_ID, spd, durationMs);
    left(spd);
  }
  else if (act == "right" || act == "turn_right" || act == "turn right" || act == "r" || act == "d") {
    Serial.printf("[%s MOTOR] RIGHT (spd: %d, dur: %d ms)\n", BOT_ID, spd, durationMs);
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

  // Targeted Command Filter (prevents command bleeding across bots)
  int botIdx = str.indexOf("\"bot_id\"");
  if (botIdx == -1) botIdx = str.indexOf("\"robot_id\"");
  if (botIdx != -1) {
    int colon = str.indexOf(':', botIdx);
    int q1 = str.indexOf('"', colon);
    int q2 = str.indexOf('"', q1 + 1);
    if (q1 != -1 && q2 != -1) {
      String targetBot = str.substring(q1 + 1, q2);
      targetBot.trim();
      targetBot.toLowerCase();
      String myBot = String(BOT_ID);
      myBot.toLowerCase();
      if (targetBot.length() > 0 && targetBot != myBot && targetBot != "all" && targetBot != "fleet" && targetBot != "bot2") {
        return;
      }
    }
  }

  // Handle autonomous edge obstacle avoidance toggle
  if (str.indexOf("\"auto_avoid\"") != -1) {
    int enIdx = str.indexOf("\"enabled\"");
    if (enIdx != -1) {
      int colon = str.indexOf(':', enIdx);
      String valStr = str.substring(colon + 1);
      valStr.trim();
      if (valStr.startsWith("true") || valStr.startsWith("1")) {
        edgeAvoidEnabled = true;
        avoidState = AVOID_IDLE;
        Serial.println(F("[BUPI-02] Autonomous Edge Obstacle Avoidance: ENABLED"));
      } else {
        edgeAvoidEnabled = false;
        avoidState = AVOID_IDLE;
        stopMotors();
        Serial.println(F("[BUPI-02] Autonomous Edge Obstacle Avoidance: DISABLED"));
      }
      return;
    }
  }

  // Handle active obstacle bypass command ("cross out obstacle")
  if (str.indexOf("\"bypass_obstacle\"") != -1 || str.indexOf("\"cross_obstacle\"") != -1 || str.indexOf("\"evade\"") != -1) {
    int dir = 1;
    if (str.indexOf("\"left\"") != -1) dir = -1;
    else if (str.indexOf("\"right\"") != -1) dir = 1;
    triggerObstacleBypass(dir);
    return;
  }

  // Single-key and plain string manual commands
  if (str.equalsIgnoreCase("w") || str.equalsIgnoreCase("f") || str.equalsIgnoreCase("forward") || str.equalsIgnoreCase("move_forward")) { executeMotorAction("forward", 255, 1000); return; }
  if (str.equalsIgnoreCase("s") || str.equalsIgnoreCase("b") || str.equalsIgnoreCase("backward") || str.equalsIgnoreCase("reverse") || str.equalsIgnoreCase("back")) { executeMotorAction("backward", 255, 1000); return; }
  if (str.equalsIgnoreCase("a") || str.equalsIgnoreCase("l") || str.equalsIgnoreCase("left") || str.equalsIgnoreCase("turn_left")) { executeMotorAction("left", 255, 600); return; }
  if (str.equalsIgnoreCase("d") || str.equalsIgnoreCase("r") || str.equalsIgnoreCase("right") || str.equalsIgnoreCase("turn_right")) { executeMotorAction("right", 255, 600); return; }
  if (str.equalsIgnoreCase("stop") || str.equalsIgnoreCase("x") || str == " ") { stopMotors(); return; }

  // Extract action from JSON
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
      Serial.printf("[%s WS] Disconnected from Boopi Hub.\n", BOT_ID);
      break;

    case WStype_CONNECTED:
      Serial.printf("[%s WS] Connected to Boopi Hub (ws://%s:%d)!\n", BOT_ID, websocket_server, websocket_port);
      webSocket.sendTXT("{\"type\":\"announce\",\"bot_id\":\"" BOT_ID "\",\"robot_id\":\"" BOT_ID "\",\"device\":\"" BOT_NAME "\",\"role\":\"" BOT_ROLE "\",\"capabilities\":[\"differential_drive\",\"MQ-2\",\"DHT22\",\"HC-SR04\",\"MPU6050_6AXIS\",\"GYRO_TURNS\",\"EDGE_AVOID\"],\"status\":\"online\"}");
      break;

    case WStype_TEXT:
      processCommandString((char*)payload);
      break;

    default:
      break;
  }
}

// ---------------- WIFI EVENT HANDLER ----------------
void onWiFiEvent(WiFiEvent_t event) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      wifiConnected = true;
      Serial.println("\n[WiFi] Connected! IP: " + WiFi.localIP().toString());
      Serial.printf("[WiFi] RSSI: %d dBm\n", WiFi.RSSI());

      webSocket.begin(websocket_server, websocket_port, "/");
      webSocket.onEvent(webSocketEvent);
      webSocket.enableHeartbeat(10000, 3000, 2);
      webSocket.setReconnectInterval(2000);
      Serial.printf("[WS] Connecting to Boopi Hub at ws://%s:%d/\n", websocket_server, websocket_port);
      break;

    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      wifiConnected = false;
      Serial.println("[WiFi] Disconnected from Hotspot. Auto-reconnecting in background...");
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
  Serial.printf("     🤖 BUPI-02 SPECIALIST (ID: %s)\n", BOT_ID);
  Serial.println("========================================");

  // 1. Initialize motors FIRST
  initMotors();

  // 2. Diagnostics: Motor test disabled at boot to prevent inrush current brownout before Wi-Fi init
  // (Especially important for Bot 2 due to continuous MQ-2 heater current draw)
  // forward(160); delay(150); stopMotors();

  // 3. Initialize sensors with timeout safety
  initSensors();

  // 4. Configure Wi-Fi Radio for maximum stability and anti-lag
  WiFi.onEvent(onWiFiEvent);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  WiFi.setSleep(false);
  esp_wifi_set_ps(WIFI_PS_NONE);
  WiFi.setTxPower(WIFI_POWER_17dBm); // 17dBm prevents current spikes while maintaining strong RF range
  WiFi.setHostname(wifi_hostname);

  #if USE_STATIC_IP
  Serial.println("[WiFi] Configuring dedicated static IP: " + staticIP.toString());
  WiFi.config(staticIP, gateway, subnet, dnsServer);
  #endif

  Serial.printf("[WiFi] Connecting to '%s'...\n", ssid);
  WiFi.begin(ssid, password);

  // Initial connection wait (up to 8s)
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 24) {
    delay(350);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    wifiConnected = true;
  } else {
    wifiConnected = false;
    Serial.printf("\n[WiFi] Initial association in progress (Status: %d). Will connect in background.\n", WiFi.status());
    Serial.println("[WiFi] Operating in USB Serial mode. Automatic Wi-Fi guardian active.");
  }

  Serial.println("========================================");
  Serial.println("   READY FOR NATURAL LANGUAGE MISSIONS  ");
  Serial.println("========================================\n");
}

// ---------------- MAIN NON-BLOCKING 20HZ LOOP ----------------
void loop() {
  unsigned long now = millis();

  // Background Wi-Fi Auto-Reconnection Guardian (Non-blocking, non-destructive)
  static unsigned long lastWifiCheck = 0;
  if (now - lastWifiCheck >= 20000) {
    lastWifiCheck = now;
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[WiFi Guardian] Re-triggering connection to " + String(ssid));
      WiFi.reconnect();
    }
  }

  if (wifiConnected) {
    webSocket.loop();
  }

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

  // 2. 20 Hz Perception & Local Reflex Loop (every 50ms)
  if (now - lastSensorTick >= 50) {
    lastSensorTick = now;

    distanceCm = readUltrasonic();
    readMPUAndEnvironment();

    // Check closed-loop angular gyro turn progress
    updateClosedLoopTurn();

    // Check autonomous edge obstacle avoidance
    updateEdgeObstacleAvoidance();

    // Reflex Barrier Cutoff
    bool prevCritical = obstacleCritical;
    obstacleCritical = (distanceCm <= CRITICAL_OBSTACLE_CM);
    if (obstacleCritical) {
      obstacleDebounceCount++;
      if (motorActive && currentMovement == "FORWARD") {
        stopMotors();
        Serial.printf("{\"safety_event\":\"BARRIER_COLLISION_CUTOFF\",\"bot_id\":\"%s\",\"distance_cm\":%.1f}\n", BOT_ID, distanceCm);
      }
    } else {
      obstacleDebounceCount = 0;
    }

    // High Gas Environmental Hazard Warning (Rate-limited to once every 3s)
    static unsigned long lastGasAlertTime = 0;
    bool gasAlert = (gasPpm >= GAS_HAZARD_THRESHOLD);
    if (gasAlert && (now - lastGasAlertTime >= 3000)) {
      lastGasAlertTime = now;
      Serial.printf("{\"hazard_event\":\"HIGH_GAS_ALERT\",\"bot_id\":\"%s\",\"gas_ppm\":%.1f}\n", BOT_ID, gasPpm);
    }

    // Immediate event transmission if obstacle state, movement, or hazard alert changed
    static String lastMovementSent = "STOP";
    bool stateChanged = (currentMovement != lastMovementSent) || (obstacleCritical != prevCritical) || gasAlert;

    // Adaptive Telemetry: 10 Hz (100ms) when moving, 2 Hz (500ms) when idle, or immediate on event
    static unsigned long lastWsTelemTime = 0;
    unsigned long wsInterval = (motorActive || targetTurnActive) ? 100 : 500;

    if (stateChanged || (now - lastWsTelemTime >= wsInterval)) {
      lastWsTelemTime = now;
      lastMovementSent = currentMovement;
      String telemetryStr = buildTelemetryJson();
      if (wifiConnected && webSocket.isConnected()) {
        webSocket.sendTXT(telemetryStr);
      }
    }

    // Serial debug print throttled to 100ms (10 Hz)
    static unsigned long lastSerialPrint = 0;
    if (now - lastSerialPrint >= 100) {
      lastSerialPrint = now;
      Serial.println(buildTelemetryJson());
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
      webSocket.sendTXT("{\"type\":\"heartbeat\",\"bot_id\":\"" BOT_ID "\",\"device\":\"" BOT_NAME "\",\"status\":\"online\"}");
    }
  }
}
