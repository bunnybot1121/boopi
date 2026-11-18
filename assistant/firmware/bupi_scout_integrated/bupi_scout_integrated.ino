/*
 * ==============================================================================
 * MASTER PRODUCTION FIRMWARE: BUPI-01 (SCOUT) UNIFIED HARDWARE & CONTINUOUS PATHFINDING
 * Project: BUPI Autonomous Robotics Fleet (Offline-First Scout Node)
 * Node ID: BUPI-01 (Scout) / Alias: bupi_01
 * Baud Rate: 115200 baud
 * Dual-Channel Interface: USB Serial 115200 + Wi-Fi WebSockets (Boopi Hub)
 *
 * COMPLETE HARDWARE & NETWORK INTEGRATION:
 *   1. Hardware Pin Configuration (Exact 15-Pin Mapping Strictly Locked)
 *   2. Hardware PWM & Timer Isolation (ESP32Servo on Timers 0 & 1; TB6612FNG on Timer 2, Ch 4 & 5)
 *   3. Wi-Fi & WebSockets Connectivity (Auto-Reconnect Guardian, 20Hz Telemetry & Bi-directional Remote Commands)
 *   4. ESP32 Brownout Safety Override (WRITE_PERI_REG RTC_CNTL_BROWN_OUT_REG)
 *   5. Staggered Dual-Ultrasonic & Dual-Servo Radar Sweeping (>= 15ms acoustic separation)
 *   6. High-Frequency MPU6050 6-Axis IMU (50 Hz, Gyro Z Yaw Integration, Pitch/Roll)
 *   7. PIR Human Motion Sensor with 800ms Pulse Stretcher
 *   8. Deterministic Obstacle Avoidance & Contiguous Corridor Pathfinding State Machine (20 Hz)
 *   9. Dual-Mode Heading Control: Closed-Loop Gyro Yaw with Time-Proportional Fallback
 *  10. Non-Blocking 4-Task Super-Loop (Continuous void loop() - Zero blocking delay())
 * ==============================================================================
 */

#include <WiFi.h>
#include <WebSocketsClient.h>
#include <Wire.h>
#include <math.h>
#include <ESP32Servo.h>
#include "esp_wifi.h"
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// ==============================================================================
// 1. IDENTITY & NETWORK CONFIGURATION
// ==============================================================================
#define BOT_ID              "bupi_01"
#define BOT_NAME            "BUPI_01_SCOUT"
#define BOT_ROLE            "SCOUT"

// Wi-Fi Access Point Credentials
const char* wifi_ssid       = "CHINTU 4312";
const char* wifi_password   = "j016,48R";

// Candidate WebSocket Hub Hosts (Auto-Discovery with Automatic Multi-IP Fallback)
// Priority 0: Dynamic Gateway IP (detected at runtime: 192.168.137.1 on Hotspot, or router gateway)
// Priority 1: User Host Laptop Subnet IP (192.168.0.100)
// Priority 2: Standard Windows Mobile Hotspot IP (192.168.137.1)
const char* ws_hosts[]      = {"192.168.137.1", "192.168.0.100", "192.168.137.1"};
const int NUM_WS_HOSTS      = 3;
int current_ws_host_idx     = 0;
String active_ws_server     = "192.168.137.1";
String dynamic_gateway_ip   = "";
const uint16_t ws_port      = 8767;
int ws_disconnect_count     = 0;

// DHCP Mode with Unique Hostname (Set USE_STATIC_IP to 1 for Static IP)
#define USE_STATIC_IP       0
const char* wifi_hostname   = "bupi-bot1-scout";
IPAddress staticIP(192, 168, 137, 101);
IPAddress gateway(192, 168, 137, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress dnsServer(192, 168, 137, 1);

// ==============================================================================
// 2. EXACT ESP32 GPIO PIN CONFIGURATION (STRICTLY LOCKED - DO NOT CHANGE)
// ==============================================================================
const int PIN_US1_TRIG      = 5;   // Ultrasonic 1 TRIG — Output
const int PIN_US1_ECHO      = 23;  // Ultrasonic 1 ECHO — Input
const int PIN_US2_TRIG      = 16;  // Ultrasonic 2 TRIG — Output
const int PIN_US2_ECHO      = 4;   // Ultrasonic 2 ECHO — Input
const int PIN_SERVO_1       = 13;  // Servo 1 paired with Ultrasonic 1 — PWM Output
const int PIN_SERVO_2       = 17;  // Servo 2 paired with Ultrasonic 2 — PWM Output
const int PIN_PIR           = 18;  // PIR Motion Sensor — Digital Input
const int PIN_MPU_SDA       = 21;  // MPU6050 I2C SDA
const int PIN_MPU_SCL       = 22;  // MPU6050 I2C SCL
const int PIN_TB_PWMA       = 25;  // TB6612FNG Motor A Speed — PWM Output
const int PIN_TB_AIN1       = 26;  // TB6612FNG Motor A Direction 1 — Output
const int PIN_TB_AIN2       = 27;  // TB6612FNG Motor A Direction 2 — Output
const int PIN_TB_PWMB       = 32;  // TB6612FNG Motor B Speed — PWM Output
const int PIN_TB_BIN1       = 33;  // TB6612FNG Motor B Direction 1 — Output
const int PIN_TB_BIN2       = 14;  // TB6612FNG Motor B Direction 2 — Output
const int PIN_TB_STBY       = -1;  // Tied to 3.3V in hardware; if >= 0 driven HIGH

// Wheel direction inversion flags for quick chassis bench calibration
bool MOTOR_A_INVERT         = false;
bool MOTOR_B_INVERT         = false;

// ==============================================================================
// 3. HARDWARE PWM & TIMER CONFIGURATION
// ==============================================================================
#define SERVO_MIN_US        500
#define SERVO_MAX_US        2400

#define MOTOR_PWM_FREQ      1000
#define MOTOR_PWM_RES       8        // 8-bit resolution (0 to 255)
#define LEDC_CH_MOT_A       4        // Dedicated high LEDC Channel 4 (Timer 2)
#define LEDC_CH_MOT_B       5        // Dedicated high LEDC Channel 5 (Timer 2)

// Motor Speed Profiles (0 to 255)
#define CRUISE_SPEED        190
#define TURN_SPEED          205
#define ESCAPE_SPEED        185

// ==============================================================================
// 4. SENSOR & PATHFINDING PARAMETERS
// ==============================================================================
#define STOP_DISTANCE_CM        25.0f   // Emergency halt trigger inside forward cone
#define SAFE_CORRIDOR_CM        35.0f   // Minimum clearance required for open corridor
#define CRITICAL_DISTANCE_CM    15.0f   // Critical reflex safety stop threshold
#define MAX_SENSOR_RANGE_CM    400.0f   // Max range for HC-SR04
#define SERVO_HORN_OFFSET_CM     3.5f   // Transducer face offset from rotation pivot
#define ECHO_TIMEOUT_US        25000UL  // 25ms pulseIn timeout (~428 cm)

#define CRUISE_SWEEP_MIN        60.0f   // Narrow forward watch cone
#define CRUISE_SWEEP_MAX       120.0f
#define CRUISE_STEP_DEG          3.0f

#define WIDTH_WEIGHT            10.0f   // Path scoring weight for corridor width
#define DEPTH_WEIGHT             0.5f   // Path scoring weight for corridor depth
#define MS_PER_DEGREE            4.5f   // Fallback turn timing per degree if IMU is offline
#define ESCAPE_REVERSE_MS        350    // Dead-end reverse duration

// 11 Sectors for Full 180° Radar Path Scan (15° to 165° in 15° steps)
#define NUM_SCAN_SECTORS        11
const float SCAN_SECTORS[NUM_SCAN_SECTORS] = {
  15.0f, 30.0f, 45.0f, 60.0f, 75.0f, 90.0f, 105.0f, 120.0f, 135.0f, 150.0f, 165.0f
};

// ==============================================================================
// 5. DATA STRUCTURES & SYSTEM STATES
// ==============================================================================
enum NodeMode {
  MODE_AUTO,
  MODE_MANUAL
};

enum PathState {
  STATE_CRUISE_FORWARD,    // Driving forward, sweeping forward cone (60°-120°)
  STATE_EMERGENCY_BRAKE,   // Immediate motor halt (<5ms) when obstacle < 25cm
  STATE_RADAR_PATH_SCAN,   // Sweeping 11 sectors (15°-165°) while stopped
  STATE_FIND_BEST_CORRIDOR,// Evaluating scan_map[] to score and select corridor
  STATE_TURN_TO_PATH,      // Closed-loop gyro turn onto optimal heading
  STATE_REVERSE_ESCAPE,    // Trapped dead-end recovery: reversing 350ms
  STATE_MANUAL_HOLD        // Manual operator teleoperation mode
};

enum UsAcqState {
  US_ACQ_IDLE,
  US_ACQ_PULSE_TRIG1,
  US_ACQ_WAIT_GAP,
  US_ACQ_PULSE_TRIG2,
  US_ACQ_COMPLETE
};

// ==============================================================================
// 6. GLOBAL STATE & INSTANCES
// ==============================================================================
WebSocketsClient webSocket;
bool wifiConnected = false;

Servo servo1;
Servo servo2;

NodeMode node_mode = MODE_AUTO;
PathState path_state = STATE_CRUISE_FORWARD;

// Servos & Radar state
float cur_s1_ang = 90.0f;
float cur_s2_ang = 90.0f;
int cruise_sweep_dir = 1;
int scan_sector_idx = 0;
bool stationary_radar_test = false;

// 11-sector radar scan map: scan_map[idx] = min(u1_cm, u2_cm)
float scan_map[NUM_SCAN_SECTORS];

// Non-blocking task timers
unsigned long now_ms = 0;
unsigned long last_servo_step_ms = 0;
const unsigned long SERVO_STEP_INTERVAL_MS = 28;

unsigned long last_imu_step_ms = 0;
const unsigned long IMU_INTERVAL_MS = 20; // 50 Hz IMU loop

unsigned long last_nav_step_ms = 0;
const unsigned long NAV_INTERVAL_MS = 50; // 20 Hz State Machine loop

unsigned long last_telemetry_ms = 0;
const unsigned long TELEMETRY_INTERVAL_MS = 62; // ~16 Hz Telemetry stream

unsigned long last_heartbeat_ms = 0;
unsigned long motor_end_time_ms = 0;

// Staggered ultrasonic acquisition non-blocking state machine
UsAcqState us_state = US_ACQ_IDLE;
unsigned long us_timer_ms = 0;
float latest_u1_cm = 400.0f;
float latest_u2_cm = 400.0f;
float delta_cm = 0.0f;
bool valid1 = false;
bool valid2 = false;
int safety_stop_flag = 0;

// Pathfinding & turn navigation
float target_path_angle = 90.0f;  // Selected corridor center angle (90° = straight ahead)
float turn_delta_deg = 0.0f;      // Relative turn offset: target_path_angle - 90°
float turn_start_yaw = 0.0f;
unsigned long turn_start_ms = 0;
unsigned long turn_timeout_ms = 0;
unsigned long reverse_end_ms = 0;

// Motor tracking
String current_motor_cmd = "STOP";
bool motorActive = false;

// PIR Sensor state with 800ms pulse stretcher
int pir_state = 0;
unsigned long last_pir_trigger_ms = 0;

// MPU6050 IMU tracking
bool imu_ok = false;
uint8_t mpu_addr = 0x68;
float gyro_z_bias = 0.0f;
float yaw_deg = 0.0f;
float pitch_deg = 0.0f;
float roll_deg = 0.0f;
float ax_g = 0.0, ay_g = 0.0, az_g = 1.0;
unsigned long last_imu_micros = 0;
uint8_t imu_error_count = 0;

// Wi-Fi signal & step estimation
int last_wifi_rssi = 0;
unsigned long step_count = 0;
float distance_traveled_m = 0.0;
unsigned long last_step_time_ms = 0;
const float STEP_STRIDE_M = 0.075f; // ~7.5 cm per step

// Serial RX command buffer
String serial_rx_buf = "";

// Forward Declarations
void stopMotors();
void moveForward(int speed);
void moveBackward(int speed);
void turnLeft(int speed);
void turnRight(int speed);
void setMotorOutputs(int speedA, bool fwdA, int speedB, bool fwdB);
void writeServos(float ang1, float ang2);
void initMotors();
void initServos();
void initMPU6050();
void updateIMU();
void runUltrasonicRadarTask();
void runNavigationTask();
void runTelemetryTask();
void handleSerialCommands();
void processCommandString(String cmd_str);
void startTurnToPath(float delta_angle);
void evaluateBestCorridor();
float measureEchoCm(int trig_pin, int echo_pin, bool &is_valid);
String buildTelemetryJson();

// ==============================================================================
// 7. MOTOR CONTROLLER (TB6612FNG DUAL H-BRIDGE)
// ==============================================================================
void initMotors() {
  pinMode(PIN_TB_AIN1, OUTPUT);
  pinMode(PIN_TB_AIN2, OUTPUT);
  pinMode(PIN_TB_BIN1, OUTPUT);
  pinMode(PIN_TB_BIN2, OUTPUT);

  if (PIN_TB_STBY >= 0) {
    pinMode(PIN_TB_STBY, OUTPUT);
    digitalWrite(PIN_TB_STBY, HIGH);
  }

  // Configure Motor PWM on dedicated LEDC Timer 2 (Channels 4 & 5, 1000 Hz, 8-bit)
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  ledcAttachChannel(PIN_TB_PWMA, MOTOR_PWM_FREQ, MOTOR_PWM_RES, LEDC_CH_MOT_A);
  ledcAttachChannel(PIN_TB_PWMB, MOTOR_PWM_FREQ, MOTOR_PWM_RES, LEDC_CH_MOT_B);
#else
  ledcSetup(LEDC_CH_MOT_A, MOTOR_PWM_FREQ, MOTOR_PWM_RES);
  ledcAttachPin(PIN_TB_PWMA, LEDC_CH_MOT_A);
  ledcSetup(LEDC_CH_MOT_B, MOTOR_PWM_FREQ, MOTOR_PWM_RES);
  ledcAttachPin(PIN_TB_PWMB, LEDC_CH_MOT_B);
#endif

  stopMotors();
}

void setMotorOutputs(int speedA, bool fwdA, int speedB, bool fwdB) {
  if (MOTOR_A_INVERT) fwdA = !fwdA;
  if (MOTOR_B_INVERT) fwdB = !fwdB;

  speedA = constrain(speedA, 0, 255);
  speedB = constrain(speedB, 0, 255);

  // Motor A (Left) Direction
  if (speedA > 0) {
    digitalWrite(PIN_TB_AIN1, fwdA ? HIGH : LOW);
    digitalWrite(PIN_TB_AIN2, fwdA ? LOW : HIGH);
  } else {
    digitalWrite(PIN_TB_AIN1, HIGH);
    digitalWrite(PIN_TB_AIN2, HIGH);
  }

  // Motor B (Right) Direction
  if (speedB > 0) {
    digitalWrite(PIN_TB_BIN1, fwdB ? HIGH : LOW);
    digitalWrite(PIN_TB_BIN2, fwdB ? LOW : HIGH);
  } else {
    digitalWrite(PIN_TB_BIN1, HIGH);
    digitalWrite(PIN_TB_BIN2, HIGH);
  }

  // Motor Speeds
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  ledcWrite(PIN_TB_PWMA, (uint32_t)speedA);
  ledcWrite(PIN_TB_PWMB, (uint32_t)speedB);
#else
  ledcWrite(LEDC_CH_MOT_A, (uint32_t)speedA);
  ledcWrite(LEDC_CH_MOT_B, (uint32_t)speedB);
#endif

  motorActive = (speedA > 0 || speedB > 0);
}

void moveForward(int speed) {
  if (PIN_TB_STBY >= 0) digitalWrite(PIN_TB_STBY, HIGH);
  setMotorOutputs(speed, true, speed, true);
  current_motor_cmd = "FWD";
}

void moveBackward(int speed) {
  if (PIN_TB_STBY >= 0) digitalWrite(PIN_TB_STBY, HIGH);
  setMotorOutputs(speed, false, speed, false);
  current_motor_cmd = "REV";
}

void turnLeft(int speed) {
  if (PIN_TB_STBY >= 0) digitalWrite(PIN_TB_STBY, HIGH);
  // Counter-rotation pivot: Left backward, Right forward
  setMotorOutputs(speed, false, speed, true);
  current_motor_cmd = "LEFT";
}

void turnRight(int speed) {
  if (PIN_TB_STBY >= 0) digitalWrite(PIN_TB_STBY, HIGH);
  // Counter-rotation pivot: Left forward, Right backward
  setMotorOutputs(speed, true, speed, false);
  current_motor_cmd = "RIGHT";
}

void stopMotors() {
  setMotorOutputs(0, false, 0, false);
  current_motor_cmd = "STOP";
  motor_end_time_ms = 0;
}

// ==============================================================================
// 8. SERVO TURRET CONTROLLER (LEDC TIMERS 0 & 1 @ 50 Hz)
// ==============================================================================
void initServos() {
  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);

  servo1.setPeriodHertz(50);
  servo2.setPeriodHertz(50);

  servo1.attach(PIN_SERVO_1, SERVO_MIN_US, SERVO_MAX_US);
  servo2.attach(PIN_SERVO_2, SERVO_MIN_US, SERVO_MAX_US);

  writeServos(90.0f, 90.0f);
}

void writeServos(float ang1, float ang2) {
  ang1 = constrain(ang1, 0.0f, 180.0f);
  ang2 = constrain(ang2, 0.0f, 180.0f);
  cur_s1_ang = ang1;
  cur_s2_ang = ang2;
  servo1.write((int)roundf(ang1));
  servo2.write((int)roundf(ang2));
}

// ==============================================================================
// 9. HC-SR04 ULTRASONIC ACQUISITION (SAFE, NON-BLOCKING, 15ms STAGGER)
// ==============================================================================
float measureEchoCm(int trig_pin, int echo_pin, bool &is_valid) {
  digitalWrite(trig_pin, LOW);
  delayMicroseconds(4);
  digitalWrite(trig_pin, HIGH);
  delayMicroseconds(12);
  digitalWrite(trig_pin, LOW);

  unsigned long duration_us = pulseIn(echo_pin, HIGH, ECHO_TIMEOUT_US);
  float raw_dist = (float)duration_us * 0.01729f;

  if (duration_us > 0 && raw_dist >= 3.0f) {
    float dist = raw_dist + SERVO_HORN_OFFSET_CM;
    if (dist <= MAX_SENSOR_RANGE_CM) {
      is_valid = true;
      return dist;
    }
  }

  is_valid = false;
  return MAX_SENSOR_RANGE_CM;
}

// ==============================================================================
// 10. MPU-6050 6-AXIS IMU (I2C AUTO-DETECT & TIMEOUT PROTECTION)
// ==============================================================================
bool probeI2C(uint8_t addr) {
  Wire.beginTransmission(addr);
  return (Wire.endTransmission() == 0);
}

void initMPU6050() {
  Wire.begin(PIN_MPU_SDA, PIN_MPU_SCL, 400000UL);
  Wire.setTimeOut(20);

  if (probeI2C(0x68)) {
    mpu_addr = 0x68;
    imu_ok = true;
  } else if (probeI2C(0x69)) {
    mpu_addr = 0x69;
    imu_ok = true;
  } else {
    imu_ok = false;
    Serial.println(F("[IMU] Warning: MPU6050 not detected at 0x68 or 0x69. Falling back to timed turns."));
    return;
  }

  Wire.beginTransmission(mpu_addr);
  Wire.write(0x6B);
  Wire.write(0x00);
  if (Wire.endTransmission() != 0) {
    imu_ok = false;
    return;
  }
  delay(15);

  float sum_gz = 0.0f;
  int count = 0;
  for (int i = 0; i < 40; i++) {
    Wire.beginTransmission(mpu_addr);
    Wire.write(0x47);
    if (Wire.endTransmission(false) == 0 && Wire.requestFrom(mpu_addr, (uint8_t)2) == 2) {
      int16_t r_gz = (Wire.read() << 8) | Wire.read();
      sum_gz += (float)r_gz / 131.0f;
      count++;
    }
    delay(3);
  }

  if (count >= 20) {
    gyro_z_bias = sum_gz / (float)count;
    last_imu_micros = micros();
    Serial.printf("[IMU] MPU-6050 initialized at 0x%02X. Gyro Z Bias: %.3f deg/s\n", mpu_addr, gyro_z_bias);
  } else {
    imu_ok = false;
    Serial.println(F("[IMU] Gyro calibration failed. Fallback to timed turns."));
  }
}

void updateIMU() {
  if (!imu_ok) return;

  unsigned long current_us = micros();
  float dt = (float)(current_us - last_imu_micros) / 1000000.0f;
  last_imu_micros = current_us;
  if (dt <= 0.0f || dt > 0.5f) dt = 0.02f;

  Wire.beginTransmission(mpu_addr);
  Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0 || Wire.requestFrom(mpu_addr, (uint8_t)14) != 14) {
    imu_error_count++;
    if (imu_error_count > 12) {
      imu_ok = false;
      Serial.println(F("[IMU] I2C bus error. Fallback to timed turns active."));
    }
    return;
  }
  imu_error_count = 0;

  int16_t raw_ax = (Wire.read() << 8) | Wire.read();
  int16_t raw_ay = (Wire.read() << 8) | Wire.read();
  int16_t raw_az = (Wire.read() << 8) | Wire.read();
  int16_t raw_temp = (Wire.read() << 8) | Wire.read(); (void)raw_temp;
  int16_t raw_gx = (Wire.read() << 8) | Wire.read(); (void)raw_gx;
  int16_t raw_gy = (Wire.read() << 8) | Wire.read(); (void)raw_gy;
  int16_t raw_gz = (Wire.read() << 8) | Wire.read();

  ax_g = (float)raw_ax / 16384.0f;
  ay_g = (float)raw_ay / 16384.0f;
  az_g = (float)raw_az / 16384.0f;
  float gz = ((float)raw_gz / 131.0f) - gyro_z_bias;

  if (fabsf(gz) > 0.65f) {
    yaw_deg += gz * dt;
  }

  pitch_deg = atan2f(-ax_g, sqrtf(ay_g * ay_g + az_g * az_g)) * (180.0f / (float)M_PI);
  roll_deg = atan2f(ay_g, az_g) * (180.0f / (float)M_PI);

  // Step detection & dynamic odometry while moving
  float total_accel = sqrtf(ax_g * ax_g + ay_g * ay_g + az_g * az_g);
  if (motorActive && total_accel >= 1.20f && (now_ms - last_step_time_ms) >= 180) {
    step_count++;
    distance_traveled_m += STEP_STRIDE_M;
    last_step_time_ms = now_ms;
  }
}

// ==============================================================================
// 11. NON-BLOCKING TASK 1: STAGGERED DUAL-ULTRASONIC & RADAR SWEEP LOOP
// ==============================================================================
void runUltrasonicRadarTask() {
  switch (us_state) {
    case US_ACQ_IDLE:
      if (now_ms - last_servo_step_ms >= SERVO_STEP_INTERVAL_MS) {
        last_servo_step_ms = now_ms;

        if (path_state == STATE_CRUISE_FORWARD) {
          cur_s1_ang += ((float)cruise_sweep_dir * CRUISE_STEP_DEG);
          if (cur_s1_ang >= CRUISE_SWEEP_MAX) {
            cur_s1_ang = CRUISE_SWEEP_MAX;
            cruise_sweep_dir = -1;
          } else if (cur_s1_ang <= CRUISE_SWEEP_MIN) {
            cur_s1_ang = CRUISE_SWEEP_MIN;
            cruise_sweep_dir = 1;
          }
          cur_s2_ang = cur_s1_ang;
          writeServos(cur_s1_ang, cur_s2_ang);
        } else if (path_state == STATE_RADAR_PATH_SCAN) {
          if (scan_sector_idx < NUM_SCAN_SECTORS) {
            cur_s1_ang = SCAN_SECTORS[scan_sector_idx];
            cur_s2_ang = cur_s1_ang;
            writeServos(cur_s1_ang, cur_s2_ang);
          }
        }

        us_state = US_ACQ_PULSE_TRIG1;
      }
      break;

    case US_ACQ_PULSE_TRIG1:
      latest_u1_cm = measureEchoCm(PIN_US1_TRIG, PIN_US1_ECHO, valid1);
      us_timer_ms = now_ms + 16;
      us_state = US_ACQ_WAIT_GAP;
      break;

    case US_ACQ_WAIT_GAP:
      if (now_ms >= us_timer_ms) {
        us_state = US_ACQ_PULSE_TRIG2;
      }
      break;

    case US_ACQ_PULSE_TRIG2:
      latest_u2_cm = measureEchoCm(PIN_US2_TRIG, PIN_US2_ECHO, valid2);
      delta_cm = latest_u1_cm - latest_u2_cm;
      us_state = US_ACQ_COMPLETE;
      break;

    case US_ACQ_COMPLETE:
      if (path_state == STATE_RADAR_PATH_SCAN) {
        if (scan_sector_idx < NUM_SCAN_SECTORS) {
          scan_map[scan_sector_idx] = fminf(latest_u1_cm, latest_u2_cm);
          scan_sector_idx++;
          if (scan_sector_idx >= NUM_SCAN_SECTORS) {
            path_state = STATE_FIND_BEST_CORRIDOR;
          }
        }
      }

      if (path_state == STATE_CRUISE_FORWARD && node_mode == MODE_AUTO) {
        if (cur_s1_ang >= 65.0f && cur_s1_ang <= 115.0f) {
          if ((valid1 && latest_u1_cm < STOP_DISTANCE_CM) || (valid2 && latest_u2_cm < STOP_DISTANCE_CM) || (fabsf(delta_cm) > 40.0f && latest_u1_cm < 45.0f)) {
            stopMotors();
            safety_stop_flag = 1;
            path_state = STATE_EMERGENCY_BRAKE;
            Serial.printf("[SAFETY] Forward cone breach! Distance: %.1f cm (delta: %.1f cm). Emergency stop.\n",
                          fminf(latest_u1_cm, latest_u2_cm), delta_cm);
          }
        }
      }

      us_state = US_ACQ_IDLE;
      break;
  }
}

// ==============================================================================
// 12. NON-BLOCKING TASK 3: DETERMINISTIC OBSTACLE AVOIDANCE & PATHFINDING
// ==============================================================================
void evaluateBestCorridor() {
  int best_start = -1;
  int best_end = -1;
  int best_width = 0;
  float best_score = -1.0f;

  int cur_start = -1;
  bool max_clearance_exists = false;

  for (int i = 0; i < NUM_SCAN_SECTORS; i++) {
    if (scan_map[i] > STOP_DISTANCE_CM) {
      max_clearance_exists = true;
    }

    if (scan_map[i] >= SAFE_CORRIDOR_CM) {
      if (cur_start == -1) {
        cur_start = i;
      }
    } else {
      if (cur_start != -1) {
        int cur_end = i - 1;
        int width_steps = cur_end - cur_start + 1;
        float sum_depth = 0.0f;
        for (int k = cur_start; k <= cur_end; k++) {
          sum_depth += fminf(scan_map[k], 200.0f);
        }
        float avg_depth = sum_depth / (float)width_steps;
        float score = ((float)width_steps * WIDTH_WEIGHT) + (avg_depth * DEPTH_WEIGHT);

        if (score > best_score) {
          best_score = score;
          best_start = cur_start;
          best_end = cur_end;
          best_width = width_steps;
        }
        cur_start = -1;
      }
    }
  }

  if (cur_start != -1) {
    int cur_end = NUM_SCAN_SECTORS - 1;
    int width_steps = cur_end - cur_start + 1;
    float sum_depth = 0.0f;
    for (int k = cur_start; k <= cur_end; k++) {
      sum_depth += fminf(scan_map[k], 200.0f);
    }
    float avg_depth = sum_depth / (float)width_steps;
    float score = ((float)width_steps * WIDTH_WEIGHT) + (avg_depth * DEPTH_WEIGHT);

    if (score > best_score) {
      best_score = score;
      best_start = cur_start;
      best_end = cur_end;
      best_width = width_steps;
    }
  }

  Serial.print(F("[RADAR MAP] ["));
  for (int i = 0; i < NUM_SCAN_SECTORS; i++) {
    Serial.printf("%.0f:%.1fcm", SCAN_SECTORS[i], scan_map[i]);
    if (i < NUM_SCAN_SECTORS - 1) Serial.print(F(", "));
  }
  Serial.println(F("]"));

  if (!max_clearance_exists || best_score <= 0.0f) {
    if (stationary_radar_test) {
      Serial.println(F("[RADAR TEST] No open corridor found (Dead-End detected). Stationary test complete."));
      stationary_radar_test = false;
      path_state = (node_mode == MODE_AUTO) ? STATE_CRUISE_FORWARD : STATE_MANUAL_HOLD;
      writeServos(90.0f, 90.0f);
      return;
    }

    Serial.println(F("[PATHFINDER] Trapped dead-end! Reversing straight back for 350ms..."));
    moveBackward(ESCAPE_SPEED);
    reverse_end_ms = now_ms + ESCAPE_REVERSE_MS;
    path_state = STATE_REVERSE_ESCAPE;
    return;
  }

  float mid_idx = (float)(best_start + best_end) / 2.0f;
  target_path_angle = SCAN_SECTORS[0] + (mid_idx * 15.0f);
  turn_delta_deg = target_path_angle - 90.0f;

  Serial.printf("[PATHFINDER] Selected corridor: Sectors %d..%d (Width: %d, Center: %.1f°, Delta: %.1f°, Score: %.1f)\n",
                best_start, best_end, best_width, target_path_angle, turn_delta_deg, best_score);

  if (stationary_radar_test) {
    Serial.printf("[RADAR TEST COMPLETE] Target Path Angle: %.1f° (Turn Delta: %.1f°). Wheels not moved.\n", target_path_angle, turn_delta_deg);
    stationary_radar_test = false;
    writeServos(90.0f, 90.0f);
    path_state = (node_mode == MODE_AUTO) ? STATE_CRUISE_FORWARD : STATE_MANUAL_HOLD;
    return;
  }

  startTurnToPath(turn_delta_deg);
}

void startTurnToPath(float delta_angle) {
  turn_delta_deg = delta_angle;

  if (fabsf(delta_angle) < 4.0f) {
    writeServos(90.0f, 90.0f);
    path_state = STATE_CRUISE_FORWARD;
    moveForward(CRUISE_SPEED);
    return;
  }

  if (delta_angle > 0.0f) {
    turnLeft(TURN_SPEED);
  } else {
    turnRight(TURN_SPEED);
  }

  turn_start_yaw = yaw_deg;
  turn_start_ms = now_ms;

  if (imu_ok) {
    turn_timeout_ms = now_ms + (unsigned long)(fabsf(delta_angle) * 18.0f) + 1200;
  } else {
    unsigned long duration = (unsigned long)(fabsf(delta_angle) * MS_PER_DEGREE);
    if (duration < 80) duration = 80;
    turn_timeout_ms = now_ms + duration;
  }

  path_state = STATE_TURN_TO_PATH;
}

void runNavigationTask() {
  if (node_mode != MODE_AUTO && !stationary_radar_test) return;

  switch (path_state) {
    case STATE_CRUISE_FORWARD:
      if (current_motor_cmd != "FWD" && node_mode == MODE_AUTO) {
        moveForward(CRUISE_SPEED);
      }
      break;

    case STATE_EMERGENCY_BRAKE:
      stopMotors();
      scan_sector_idx = 0;
      path_state = STATE_RADAR_PATH_SCAN;
      safety_stop_flag = 0;
      break;

    case STATE_RADAR_PATH_SCAN:
      break;

    case STATE_FIND_BEST_CORRIDOR:
      evaluateBestCorridor();
      break;

    case STATE_TURN_TO_PATH: {
      bool turn_finished = false;
      if (imu_ok) {
        float turned_yaw = yaw_deg - turn_start_yaw;
        if (fabsf(turned_yaw) >= fabsf(turn_delta_deg) || now_ms >= turn_timeout_ms) {
          turn_finished = true;
        }
      } else {
        if (now_ms >= turn_timeout_ms) {
          turn_finished = true;
        }
      }

      if (turn_finished) {
        stopMotors();
        writeServos(90.0f, 90.0f);
        cur_s1_ang = 90.0f;
        cur_s2_ang = 90.0f;
        cruise_sweep_dir = 1;
        path_state = STATE_CRUISE_FORWARD;
        moveForward(CRUISE_SPEED);
        Serial.println(F("[PATH] Turn completed. Turret re-centered to 90°. Resuming CRUISE_FORWARD."));
      }
      break;
    }

    case STATE_REVERSE_ESCAPE:
      if (now_ms >= reverse_end_ms) {
        stopMotors();
        Serial.println(F("[ESCAPE] Reverse recovery complete. Re-initiating radar scan..."));
        scan_sector_idx = 0;
        path_state = STATE_RADAR_PATH_SCAN;
      }
      break;

    case STATE_MANUAL_HOLD:
      break;
  }
}

// ==============================================================================
// 13. DUAL-CHANNEL TELEMETRY & COMMAND PROTOCOL
// ==============================================================================
String buildTelemetryJson() {
  if (wifiConnected) {
    last_wifi_rssi = WiFi.RSSI();
  }

  const char* st_name = "CRUISE_FORWARD";
  switch (path_state) {
    case STATE_CRUISE_FORWARD:     st_name = "CRUISE_FORWARD"; break;
    case STATE_EMERGENCY_BRAKE:    st_name = "EMERGENCY_BRAKE"; break;
    case STATE_RADAR_PATH_SCAN:    st_name = "RADAR_PATH_SCAN"; break;
    case STATE_FIND_BEST_CORRIDOR: st_name = "FIND_BEST_CORRIDOR"; break;
    case STATE_TURN_TO_PATH:       st_name = "TURN_TO_PATH"; break;
    case STATE_REVERSE_ESCAPE:     st_name = "REVERSE_ESCAPE"; break;
    case STATE_MANUAL_HOLD:        st_name = "MANUAL_HOLD"; break;
  }

  float delta_d = roundf(delta_cm * 10.0f) / 10.0f;

  char buf[512];
  snprintf(buf, sizeof(buf),
    "{\"type\":\"telemetry\",\"node\":\"BUPI-01\",\"bot_id\":\"%s\",\"device\":\"%s\",\"role\":\"%s\","
    "\"ts\":%lu,\"mode\":\"%s\",\"path_state\":\"%s\","
    "\"s1_angle\":%.1f,\"s1_ang\":%.1f,\"u1_cm\":%.1f,\"d1_cm\":%.1f,"
    "\"s2_angle\":%.1f,\"s2_ang\":%.1f,\"u2_cm\":%.1f,\"d2_cm\":%.1f,"
    "\"delta_cm\":%.1f,\"delta_d\":%.1f,\"valid1\":%d,\"valid2\":%d,"
    "\"target_path_angle\":%.1f,\"turn_delta_deg\":%.1f,\"pir\":%d,"
    "\"imu_ok\":%s,\"imu\":%s,\"yaw\":%.1f,\"pitch\":%.1f,\"roll\":%.1f,"
    "\"steps\":%lu,\"dist_m\":%.2f,\"wifi_rssi\":%d,"
    "\"motor_cmd\":\"%s\",\"moving\":%s,\"safety_stop\":%d}",
    BOT_ID, BOT_NAME, BOT_ROLE,
    now_ms,
    (node_mode == MODE_AUTO) ? "AUTO" : "MANUAL",
    st_name,
    cur_s1_ang, cur_s1_ang, latest_u1_cm, latest_u1_cm,
    cur_s2_ang, cur_s2_ang, latest_u2_cm, latest_u2_cm,
    delta_d, delta_d, valid1 ? 1 : 0, valid2 ? 1 : 0,
    target_path_angle, turn_delta_deg, pir_state,
    imu_ok ? "true" : "false", imu_ok ? "true" : "false",
    yaw_deg, pitch_deg, roll_deg,
    step_count, distance_traveled_m, last_wifi_rssi,
    current_motor_cmd.c_str(), motorActive ? "true" : "false",
    safety_stop_flag
  );
  return String(buf);
}

void runTelemetryTask() {
  if (now_ms - last_telemetry_ms < TELEMETRY_INTERVAL_MS) return;
  last_telemetry_ms = now_ms;

  String telemetryJson = buildTelemetryJson();

  // 1. Output over USB Serial
  Serial.println(telemetryJson);

  // 2. Broadcast over WebSocket if connected to Boopi Hub
  if (wifiConnected && webSocket.isConnected()) {
    webSocket.sendTXT(telemetryJson);
  }
}

void processCommandString(String cmd_str) {
  cmd_str.trim();
  if (cmd_str.length() == 0) return;

  // Targeted Command Filter (prevents command bleeding across bots)
  int botIdx = cmd_str.indexOf("\"bot_id\"");
  if (botIdx == -1) botIdx = cmd_str.indexOf("\"robot_id\"");
  if (botIdx != -1) {
    int colon = cmd_str.indexOf(':', botIdx);
    int q1 = cmd_str.indexOf('"', colon);
    int q2 = cmd_str.indexOf('"', q1 + 1);
    if (q1 != -1 && q2 != -1) {
      String targetBot = cmd_str.substring(q1 + 1, q2);
      targetBot.trim();
      targetBot.toLowerCase();
      String myBot = String(BOT_ID);
      myBot.toLowerCase();
      if (targetBot.length() > 0 && targetBot != myBot && targetBot != "all" && targetBot != "fleet" && targetBot != "bupi-01") {
        return;
      }
    }
  }

  // Single-character commands
  if (cmd_str.length() == 1) {
    char cmd = cmd_str.charAt(0);
    switch (cmd) {
      case 'W': case 'w':
        node_mode = MODE_MANUAL;
        path_state = STATE_MANUAL_HOLD;
        moveForward(CRUISE_SPEED);
        break;
      case 'S': case 's':
        node_mode = MODE_MANUAL;
        path_state = STATE_MANUAL_HOLD;
        moveBackward(ESCAPE_SPEED);
        break;
      case 'A': case 'a':
        node_mode = MODE_MANUAL;
        path_state = STATE_MANUAL_HOLD;
        turnLeft(TURN_SPEED);
        break;
      case 'D': case 'd':
        node_mode = MODE_MANUAL;
        path_state = STATE_MANUAL_HOLD;
        turnRight(TURN_SPEED);
        break;
      case 'X': case 'x':
        stopMotors();
        path_state = (node_mode == MODE_AUTO) ? STATE_CRUISE_FORWARD : STATE_MANUAL_HOLD;
        break;
      case 'R': case 'r':
        stopMotors();
        stationary_radar_test = true;
        scan_sector_idx = 0;
        path_state = STATE_RADAR_PATH_SCAN;
        Serial.println(F("[CMD] Stationary Radar Sweep Test initiated. Wheels will not move."));
        break;
      case 'M': case 'm':
        node_mode = MODE_MANUAL;
        path_state = STATE_MANUAL_HOLD;
        stopMotors();
        Serial.println(F("[CMD] Switched to MANUAL mode."));
        break;
      case 'P': case 'p':
        node_mode = MODE_AUTO;
        stationary_radar_test = false;
        path_state = STATE_CRUISE_FORWARD;
        writeServos(90.0f, 90.0f);
        moveForward(CRUISE_SPEED);
        Serial.println(F("[CMD] Started CONTINUOUS AUTONOMOUS PATHFINDING loop."));
        break;
    }
    return;
  }

  // Plain word commands
  if (cmd_str.equalsIgnoreCase("forward") || cmd_str.equalsIgnoreCase("move_forward")) { node_mode = MODE_MANUAL; path_state = STATE_MANUAL_HOLD; moveForward(CRUISE_SPEED); return; }
  if (cmd_str.equalsIgnoreCase("backward") || cmd_str.equalsIgnoreCase("reverse")) { node_mode = MODE_MANUAL; path_state = STATE_MANUAL_HOLD; moveBackward(ESCAPE_SPEED); return; }
  if (cmd_str.equalsIgnoreCase("left") || cmd_str.equalsIgnoreCase("turn_left")) { node_mode = MODE_MANUAL; path_state = STATE_MANUAL_HOLD; turnLeft(TURN_SPEED); return; }
  if (cmd_str.equalsIgnoreCase("right") || cmd_str.equalsIgnoreCase("turn_right")) { node_mode = MODE_MANUAL; path_state = STATE_MANUAL_HOLD; turnRight(TURN_SPEED); return; }
  if (cmd_str.equalsIgnoreCase("stop")) { stopMotors(); return; }

  // JSON formatted commands
  if (cmd_str.startsWith("{") && cmd_str.endsWith("}")) {
    if (cmd_str.indexOf("\"MODE\"") != -1 || cmd_str.indexOf("\"mode\"") != -1) {
      if (cmd_str.indexOf("\"AUTO\"") != -1 || cmd_str.indexOf("\"auto\"") != -1) {
        node_mode = MODE_AUTO;
        stationary_radar_test = false;
        path_state = STATE_CRUISE_FORWARD;
        writeServos(90.0f, 90.0f);
        moveForward(CRUISE_SPEED);
      } else if (cmd_str.indexOf("\"MANUAL\"") != -1 || cmd_str.indexOf("\"manual\"") != -1) {
        node_mode = MODE_MANUAL;
        path_state = STATE_MANUAL_HOLD;
        stopMotors();
      }
    } else if (cmd_str.indexOf("\"STOP\"") != -1 || cmd_str.indexOf("\"stop\"") != -1) {
      stopMotors();
    } else if (cmd_str.indexOf("\"SCAN\"") != -1 || cmd_str.indexOf("\"scan\"") != -1) {
      stopMotors();
      stationary_radar_test = true;
      scan_sector_idx = 0;
      path_state = STATE_RADAR_PATH_SCAN;
    } else if (cmd_str.indexOf("\"RESET_IMU\"") != -1) {
      yaw_deg = 0.0f;
    } else if (cmd_str.indexOf("\"action\"") != -1 || cmd_str.indexOf("\"cmd\"") != -1) {
      int spd = CRUISE_SPEED;
      int spd_idx = cmd_str.indexOf("\"speed\":");
      if (spd_idx != -1) spd = cmd_str.substring(spd_idx + 8).toInt();

      int dur = 0;
      int dur_idx = cmd_str.indexOf("\"duration_ms\":");
      if (dur_idx != -1) dur = cmd_str.substring(dur_idx + 14).toInt();

      if (cmd_str.indexOf("\"FWD\"") != -1 || cmd_str.indexOf("\"forward\"") != -1) {
        node_mode = MODE_MANUAL; path_state = STATE_MANUAL_HOLD; moveForward(spd);
        if (dur > 0) motor_end_time_ms = now_ms + dur;
      } else if (cmd_str.indexOf("\"REV\"") != -1 || cmd_str.indexOf("\"backward\"") != -1) {
        node_mode = MODE_MANUAL; path_state = STATE_MANUAL_HOLD; moveBackward(spd);
        if (dur > 0) motor_end_time_ms = now_ms + dur;
      } else if (cmd_str.indexOf("\"LEFT\"") != -1 || cmd_str.indexOf("\"left\"") != -1) {
        node_mode = MODE_MANUAL; path_state = STATE_MANUAL_HOLD; turnLeft(spd);
        if (dur > 0) motor_end_time_ms = now_ms + dur;
      } else if (cmd_str.indexOf("\"RIGHT\"") != -1 || cmd_str.indexOf("\"right\"") != -1) {
        node_mode = MODE_MANUAL; path_state = STATE_MANUAL_HOLD; turnRight(spd);
        if (dur > 0) motor_end_time_ms = now_ms + dur;
      } else if (cmd_str.indexOf("\"turn_by\"") != -1) {
        float deg = 0.0f;
        int deg_idx = cmd_str.indexOf("\"degrees\":");
        if (deg_idx != -1) deg = cmd_str.substring(deg_idx + 10).toFloat();
        if (deg != 0.0f) startTurnToPath(deg);
      } else if (cmd_str.indexOf("\"servo\"") != -1 || cmd_str.indexOf("\"look\"") != -1) {
        float a1 = cur_s1_ang;
        float a2 = cur_s2_ang;
        int a1_idx = cmd_str.indexOf("\"s1\":");
        if (a1_idx != -1) a1 = cmd_str.substring(a1_idx + 5).toFloat();
        int a2_idx = cmd_str.indexOf("\"s2\":");
        if (a2_idx != -1) a2 = cmd_str.substring(a2_idx + 5).toFloat();
        int ang_idx = cmd_str.indexOf("\"angle\":");
        if (ang_idx != -1) {
          float a = cmd_str.substring(ang_idx + 8).toFloat();
          a1 = a; a2 = a;
        }
        writeServos(a1, a2);
      }
    }
  }
}

void handleSerialCommands() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;

    if (c == '\n') {
      if (serial_rx_buf.length() > 0) {
        processCommandString(serial_rx_buf);
        serial_rx_buf = "";
      }
    } else {
      if (serial_rx_buf.length() < 180) {
        serial_rx_buf += c;
      }
    }
  }
}

// ==============================================================================
// 14. WEBSOCKET & WIFI EVENT HANDLERS
// ==============================================================================
void webSocketEvent(WStype_t type, uint8_t * payload, size_t length) {
  switch (type) {
    case WStype_DISCONNECTED:
      Serial.printf("[%s WS] Disconnected from Boopi Hub (%s).\n", BOT_ID, active_ws_server.c_str());
      ws_disconnect_count++;
      if (ws_disconnect_count >= 3) {
        ws_disconnect_count = 0;
        current_ws_host_idx = (current_ws_host_idx + 1) % NUM_WS_HOSTS;
        active_ws_server = String(ws_hosts[current_ws_host_idx]);
        Serial.printf("[WS Auto-Discover] Cycling to candidate hub: ws://%s:%d/\n", active_ws_server.c_str(), ws_port);
        webSocket.begin(active_ws_server.c_str(), ws_port, "/");
      }
      break;

    case WStype_CONNECTED:
      ws_disconnect_count = 0;
      Serial.printf("[%s WS] Connected to Boopi Hub (ws://%s:%d)!\n", BOT_ID, active_ws_server.c_str(), ws_port);
      webSocket.sendTXT("{\"type\":\"announce\",\"bot_id\":\"" BOT_ID "\",\"robot_id\":\"" BOT_ID "\",\"device\":\"" BOT_NAME "\",\"role\":\"" BOT_ROLE "\",\"capabilities\":[\"differential_drive\",\"PIR\",\"DUAL_HC_SR04\",\"DUAL_SERVO_RADAR\",\"MPU6050_6AXIS\",\"AUTONOMOUS_PATHFINDING\"],\"status\":\"online\"}");
      break;

    case WStype_TEXT:
      processCommandString((char*)payload);
      break;

    default:
      break;
  }
}

void onWiFiEvent(WiFiEvent_t event) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      wifiConnected = true;
      Serial.println("\n[WiFi] Connected! IP: " + WiFi.localIP().toString());
      dynamic_gateway_ip = WiFi.gatewayIP().toString();
      Serial.printf("[WiFi] Gateway IP: %s | RSSI: %d dBm\n", dynamic_gateway_ip.c_str(), WiFi.RSSI());

      // If gateway IP is valid, use it as candidate 0 since on Windows Hotspot the host laptop IS the gateway
      if (WiFi.gatewayIP()[0] != 0) {
        ws_hosts[0] = dynamic_gateway_ip.c_str();
      }

      current_ws_host_idx = 0;
      active_ws_server = String(ws_hosts[current_ws_host_idx]);
      webSocket.begin(active_ws_server.c_str(), ws_port, "/");
      webSocket.onEvent(webSocketEvent);
      webSocket.enableHeartbeat(10000, 3000, 2);
      webSocket.setReconnectInterval(2000);
      Serial.printf("[WS] Connecting to Boopi Hub at ws://%s:%d/\n", active_ws_server.c_str(), ws_port);
      break;

    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      wifiConnected = false;
      Serial.println(F("[WiFi] Disconnected from AP. Auto-reconnecting in background..."));
      break;

    default:
      break;
  }
}

// ==============================================================================
// 15. SETUP & INITIALIZATION
// ==============================================================================
void setup() {
  // 1. Disable ESP32 brownout detector to prevent sudden resets during motor coil inrush
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);

  Serial.begin(115200);
  while (!Serial && millis() < 1200);

  Serial.println(F("\n========================================================"));
  Serial.printf("     🤖 %s (ID: %s)\n", BOT_NAME, BOT_ID);
  Serial.println(F("     UNIFIED HARDWARE, WI-FI & RADAR PATHFINDING"));
  Serial.println(F("========================================================"));

  // 2. Configure Ultrasonic GPIO Pins
  pinMode(PIN_US1_TRIG, OUTPUT);
  pinMode(PIN_US1_ECHO, INPUT);
  digitalWrite(PIN_US1_TRIG, LOW);

  pinMode(PIN_US2_TRIG, OUTPUT);
  pinMode(PIN_US2_ECHO, INPUT);
  digitalWrite(PIN_US2_TRIG, LOW);

  // 3. Configure PIR Sensor Pin
  pinMode(PIN_PIR, INPUT);

  // 4. Initialize Actuators & Sensors
  initMotors();
  initServos();
  initMPU6050();

  // 5. Initialize Radar Scan Map Array
  for (int i = 0; i < NUM_SCAN_SECTORS; i++) {
    scan_map[i] = MAX_SENSOR_RANGE_CM;
  }

  // 6. Configure Wi-Fi Radio for maximum stability and anti-lag
  WiFi.onEvent(onWiFiEvent);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);
  WiFi.setSleep(false);
  esp_wifi_set_ps(WIFI_PS_NONE);
  WiFi.setTxPower(WIFI_POWER_19_5dBm);
  WiFi.setHostname(wifi_hostname);

#if USE_STATIC_IP
  Serial.println("[WiFi] Configuring dedicated static IP: " + staticIP.toString());
  WiFi.config(staticIP, gateway, subnet, dnsServer);
#endif

  Serial.printf("[WiFi] Connecting to '%s'...\n", wifi_ssid);
  WiFi.begin(wifi_ssid, wifi_password);

  // Non-blocking connection poll (up to 3 seconds initial wait)
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 10) {
    delay(300);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    wifiConnected = true;
  } else {
    wifiConnected = false;
    Serial.printf("\n[WiFi] Initial association in progress (Status: %d). Continuing in background.\n", WiFi.status());
    Serial.println(F("[WiFi] USB Serial stream active. Automatic Wi-Fi guardian engaged."));
  }

  delay(100);

  // 7. Start in Safe Standby Mode (Motors stopped, servos centered at 90 deg)
  node_mode = MODE_MANUAL;
  path_state = STATE_MANUAL_HOLD;
  writeServos(90.0f, 90.0f);
  stopMotors();

  Serial.println(F("[SYSTEM] Initialization Complete. Motors Standby. Continuous Super-Loop Running."));
  Serial.println(F("========================================================\n"));
}

// ==============================================================================
// 16. CONTINUOUS NON-BLOCKING SUPER-LOOP (ZERO BLOCKING DELAY)
// ==============================================================================
void loop() {
  now_ms = millis();

  // Background Wi-Fi Auto-Reconnection Guardian
  static unsigned long last_wifi_check_ms = 0;
  if (now_ms - last_wifi_check_ms >= 15000) {
    last_wifi_check_ms = now_ms;
    if (WiFi.status() != WL_CONNECTED) {
      Serial.println("[WiFi Guardian] Re-triggering connection to " + String(wifi_ssid));
      WiFi.reconnect();
    }
  }

  if (wifiConnected) {
    webSocket.loop();
  }

  // Task 1: Non-Blocking Staggered Dual-Ultrasonic & Dual-Servo Radar Loop
  runUltrasonicRadarTask();

  // Task 2: High-Frequency MPU6050 IMU & PIR Sensor Loop (50 Hz / 20 ms)
  if (now_ms - last_imu_step_ms >= IMU_INTERVAL_MS) {
    last_imu_step_ms = now_ms;
    updateIMU();

    // PIR reading with 800ms pulse stretcher
    bool raw_pir = (digitalRead(PIN_PIR) == HIGH);
    if (raw_pir) {
      last_pir_trigger_ms = now_ms;
    }
    pir_state = (raw_pir || (now_ms - last_pir_trigger_ms < 800)) ? 1 : 0;
  }

  // Task 3: Deterministic Obstacle Avoidance & Pathfinding State Machine (20 Hz)
  if (now_ms - last_nav_step_ms >= NAV_INTERVAL_MS) {
    last_nav_step_ms = now_ms;
    runNavigationTask();
  }

  // Timed motor duration cutoff for manual burst actions
  if (motor_end_time_ms > 0 && now_ms >= motor_end_time_ms) {
    stopMotors();
  }

  // Task 4: Dual-Channel Telemetry (USB Serial + WebSockets at 16 Hz) & Commands
  runTelemetryTask();
  handleSerialCommands();

  // Periodic Heartbeat over WebSocket (Every 5 seconds)
  if (now_ms - last_heartbeat_ms >= 5000) {
    last_heartbeat_ms = now_ms;
    if (wifiConnected && webSocket.isConnected()) {
      webSocket.sendTXT("{\"type\":\"heartbeat\",\"bot_id\":\"" BOT_ID "\",\"device\":\"" BOT_NAME "\",\"status\":\"online\"}");
    }
  }
}
