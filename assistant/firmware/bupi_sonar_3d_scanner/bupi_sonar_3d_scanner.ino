/*
 * ==============================================================================
 * BUPI DUAL-ULTRASONIC + DUAL-SERVO 2.5D/3D SPATIAL SCANNER FIRMWARE
 * Project: BUPI (BOPI) Disaster-Response & Autonomous Reconnaissance Robotics
 * Target: ESP32 Microcontroller (Zero External Library Conflicts)
 *
 * HARDWARE PINOUT:
 *   - Sensor 1 (Low / Primary Beam):  TRIG_1 = GPIO 5,  ECHO_1 = GPIO 18 (Level Shifted)
 *   - Sensor 2 (High / Tilted Beam):   TRIG_2 = GPIO 19, ECHO_2 = GPIO 23 (Labeled D23 on silkscreen; or VP)
 *   - Servo 1 (Azimuth / Yaw 1):       GPIO 13 (50 Hz Hardware PWM)
 *   - Servo 2 (Elevation / Yaw 2):     GPIO 16 (50 Hz Hardware PWM)
 *   - MPU6050 IMU (Optional Auto-ID): SDA = GPIO 21,  SCL = GPIO 22 (0x68 / 0x69)
 *
 * CRITICAL EMBEDDED REALITIES:
 *   1. Anti-Brownout Staggered Motion: Servos stepped sequentially with 15ms gap.
 *   2. Anti-Crosstalk Acoustic Firing: Sensor 1 pings -> 12ms delay -> Sensor 2 pings.
 *   3. Non-Blocking Ping Timeout: 25,000 us (~400 cm ceiling) prevents loop lockup.
 *   4. 3-Sample Rolling Median Filter: Discards acoustic reflections and phase noise.
 *   5. Deterministic Tier-1 Safety Stop: Triggered immediately if valid distance < 18cm.
 *   6. Multi-Scan Modes: STACKED_3D, OPPOSED_360, PITCH_TILT_3D.
 * ==============================================================================
 */

#include <Arduino.h>
#include <Wire.h>

// ------------------------------------------------------------------------------
// HARDWARE PIN DEFINITIONS
// ------------------------------------------------------------------------------
#define TRIG_1_PIN     5
#define ECHO_1_PIN     18

#define TRIG_2_PIN     19
#define ECHO_2_PIN     23    // Labeled D23 on board (Universally present on 30-pin & 38-pin boards)

#define SERVO_1_PIN    13
#define SERVO_2_PIN    16

#define I2C_SDA_PIN    21
#define I2C_SCL_PIN    22

// ------------------------------------------------------------------------------
// SERVO PWM CONFIGURATION (50 Hz, 14-bit resolution, 500us to 2400us)
// ------------------------------------------------------------------------------
#define SERVO_PWM_FREQ       50
#define SERVO_PWM_RES        14     // 0 to 16383
#define SERVO_CH_1           0
#define SERVO_CH_2           1

#define SERVO_MIN_US         500
#define SERVO_MAX_US         2400
#define SERVO_PERIOD_US      20000

// ------------------------------------------------------------------------------
// OPERATIONAL SCAN MODES
// ------------------------------------------------------------------------------
enum ScanMode {
  MODE_STACKED_3D = 0,    // Both servos sweep identical forward sector in sync (Low + High planes)
  MODE_OPPOSED_360 = 1,   // Servo 1 scans Front (0-180), Servo 2 faces Rear (+180 offset)
  MODE_PITCH_TILT_3D = 2  // Servo 1 sweeps Yaw (45-135), Servo 2 steps Pitch (0 to +30 deg)
};

// ------------------------------------------------------------------------------
// GLOBAL CONFIGURATION STATE
// ------------------------------------------------------------------------------
struct ScanConfig {
  ScanMode mode        = MODE_STACKED_3D;
  int min_ang          = 45;
  int max_ang          = 135;
  int step_deg         = 3;
  int settle_ms        = 25;
  bool sweep_enabled   = true;
  bool center_locked   = false;
  int hold_angle       = 90;
  int pitch_min        = 0;
  int pitch_max        = 30;
  int pitch_step       = 6;
} cfg;

// Turret sweep runtime state
int cur_s1_ang = 90;
int cur_s2_ang = 90;
int cur_pitch_ang = 10;
int s1_sweep_dir = 1;     // +1: Sweeping Left, -1: Sweeping Right
int pitch_dir = 1;

// MPU6050 state
bool imu_detected = false;
uint8_t imu_address = 0x68;
float gyro_z_bias = 0.0f;
float gyro_y_bias = 0.0f;
float estimated_yaw = 0.0f;
float estimated_pitch = 0.0f;
unsigned long last_imu_us = 0;

// Rolling buffers for 3-sample median filter
float s1_samples[3] = {400.0f, 400.0f, 400.0f};
float s2_samples[3] = {400.0f, 400.0f, 400.0f};
uint8_t sample_idx = 0;

// ------------------------------------------------------------------------------
// LEDC HARDWARE PWM DRIVER (Core 2.x & 3.x Universal Compatibility)
// ------------------------------------------------------------------------------
uint32_t angleToDuty(int angle_deg) {
  angle_deg = constrain(angle_deg, 0, 180);
  uint32_t pulse_us = SERVO_MIN_US + (uint32_t)((SERVO_MAX_US - SERVO_MIN_US) * angle_deg / 180L);
  uint32_t max_duty = (1 << SERVO_PWM_RES) - 1;
  return (pulse_us * max_duty) / SERVO_PERIOD_US;
}

void initServoPWM() {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  ledcAttach(SERVO_1_PIN, SERVO_PWM_FREQ, SERVO_PWM_RES);
  ledcAttach(SERVO_2_PIN, SERVO_PWM_FREQ, SERVO_PWM_RES);
#else
  ledcSetup(SERVO_CH_1, SERVO_PWM_FREQ, SERVO_PWM_RES);
  ledcAttachPin(SERVO_1_PIN, SERVO_CH_1);

  ledcSetup(SERVO_CH_2, SERVO_PWM_FREQ, SERVO_PWM_RES);
  ledcAttachPin(SERVO_2_PIN, SERVO_CH_2);
#endif
}

void writeServo1(int angle_deg) {
  uint32_t duty = angleToDuty(angle_deg);
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  ledcWrite(SERVO_1_PIN, duty);
#else
  ledcWrite(SERVO_CH_1, duty);
#endif
  cur_s1_ang = angle_deg;
}

void writeServo2(int angle_deg) {
  uint32_t duty = angleToDuty(angle_deg);
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  ledcWrite(SERVO_2_PIN, duty);
#else
  ledcWrite(SERVO_CH_2, duty);
#endif
  cur_s2_ang = angle_deg;
}

// ------------------------------------------------------------------------------
// STAGGERED MOTION DRIVER (Anti-Brownout Current Limiting)
// ------------------------------------------------------------------------------
void moveServosStaggered(int target_s1, int target_s2) {
  writeServo1(target_s1);
  delay(15); // Anti-brownout: stagger motor current surges
  writeServo2(target_s2);
  delay(cfg.settle_ms); // Allow acoustic mount to physically settle
}

// ------------------------------------------------------------------------------
// HC-SR04 TIME-OF-FLIGHT TRANSDUCER DRIVER
// ------------------------------------------------------------------------------
float fireSingleUltrasonic(uint8_t trig_pin, uint8_t echo_pin, bool &is_valid) {
  digitalWrite(trig_pin, LOW);
  delayMicroseconds(4);
  digitalWrite(trig_pin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trig_pin, LOW);

  // 25,000 us timeout (~430 cm at 343 m/s) prevents CPU blocking on echo loss
  unsigned long duration_us = pulseIn(echo_pin, HIGH, 25000UL);

  if (duration_us == 0) {
    is_valid = false;
    return 400.0f;
  }

  float dist_cm = (float)duration_us * 0.0343f / 2.0f;
  if (dist_cm < 2.0f || dist_cm > 400.0f) {
    is_valid = false;
    return 400.0f;
  }

  is_valid = true;
  return dist_cm;
}

float median3(float a, float b, float c) {
  if ((a <= b && b <= c) || (c <= b && b <= a)) return b;
  if ((b <= a && a <= c) || (c <= a && a <= b)) return a;
  return c;
}

// ------------------------------------------------------------------------------
// MPU6050 RAW I2C DRIVER (Optional Inertial Stabilization)
// ------------------------------------------------------------------------------
bool checkI2C(uint8_t addr) {
  Wire.beginTransmission(addr);
  return (Wire.endTransmission() == 0);
}

void initMPU6050() {
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, 400000UL);
  Wire.setClock(400000);

  if (checkI2C(0x68)) {
    imu_address = 0x68;
    imu_detected = true;
  } else if (checkI2C(0x69)) {
    imu_address = 0x69;
    imu_detected = true;
  } else {
    imu_detected = false;
    return;
  }

  // Wake MPU6050 (PWR_MGMT_1 = 0)
  Wire.beginTransmission(imu_address);
  Wire.write(0x6B);
  Wire.write(0x00);
  Wire.endTransmission();
  delay(20);

  // Calibrate resting gyro bias over 50 samples
  float sum_z = 0.0f;
  float sum_y = 0.0f;
  for (int i = 0; i < 50; i++) {
    Wire.beginTransmission(imu_address);
    Wire.write(0x45); // GYRO_YOUT_H
    Wire.endTransmission(false);
    Wire.requestFrom(imu_address, (uint8_t)4);
    if (Wire.available() >= 4) {
      int16_t gy = (Wire.read() << 8) | Wire.read();
      int16_t gz = (Wire.read() << 8) | Wire.read();
      sum_y += (float)gy / 131.0f;
      sum_z += (float)gz / 131.0f;
    }
    delay(4);
  }
  gyro_y_bias = sum_y / 50.0f;
  gyro_z_bias = sum_z / 50.0f;
  last_imu_us = micros();
}

void updateIMU() {
  if (!imu_detected) return;
  unsigned long now_us = micros();
  float dt = (float)(now_us - last_imu_us) / 1000000.0f;
  last_imu_us = now_us;
  if (dt <= 0.0f || dt > 0.5f) dt = 0.02f;

  Wire.beginTransmission(imu_address);
  Wire.write(0x45); // GYRO_YOUT_H
  Wire.endTransmission(false);
  Wire.requestFrom(imu_address, (uint8_t)4);
  if (Wire.available() >= 4) {
    int16_t gy = (Wire.read() << 8) | Wire.read();
    int16_t gz = (Wire.read() << 8) | Wire.read();
    float rate_y = ((float)gy / 131.0f) - gyro_y_bias;
    float rate_z = ((float)gz / 131.0f) - gyro_z_bias;

    if (abs(rate_y) > 0.8f) estimated_pitch += rate_y * dt;
    if (abs(rate_z) > 0.8f) estimated_yaw += rate_z * dt;
  }
}

// ------------------------------------------------------------------------------
// INCOMING SERIAL JSON COMMAND PARSER
// ------------------------------------------------------------------------------
void handleSerialCommands() {
  while (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0 || line.charAt(0) != '{') continue;

    // Parse command: SCAN_CFG or SERVO_CFG
    if (line.indexOf("\"cmd\"") != -1) {
      if (line.indexOf("\"center_90\":1") != -1 || line.indexOf("\"center\":true") != -1) {
        cfg.center_locked = true;
        cfg.sweep_enabled = false;
        moveServosStaggered(90, 90);
        continue;
      }
      if (line.indexOf("\"center_90\":0") != -1 || line.indexOf("\"resume\":true") != -1) {
        cfg.center_locked = false;
        cfg.sweep_enabled = true;
      }

      // Mode configuration
      if (line.indexOf("\"mode\":\"STACKED_3D\"") != -1) cfg.mode = MODE_STACKED_3D;
      else if (line.indexOf("\"mode\":\"OPPOSED_360\"") != -1) cfg.mode = MODE_OPPOSED_360;
      else if (line.indexOf("\"mode\":\"PITCH_TILT_3D\"") != -1) cfg.mode = MODE_PITCH_TILT_3D;

      // Min/Max angles
      int idx_min = line.indexOf("\"min_ang\":");
      if (idx_min != -1) cfg.min_ang = line.substring(idx_min + 10).toInt();

      int idx_max = line.indexOf("\"max_ang\":");
      if (idx_max != -1) cfg.max_ang = line.substring(idx_max + 10).toInt();

      int idx_step = line.indexOf("\"step\":");
      if (idx_step != -1) cfg.step_deg = line.substring(idx_step + 7).toInt();

      int idx_en = line.indexOf("\"sweep_en\":");
      if (idx_en != -1) cfg.sweep_enabled = (line.substring(idx_en + 11).toInt() == 1);

      // Clamp bounds
      cfg.min_ang = constrain(cfg.min_ang, 0, 90);
      cfg.max_ang = constrain(cfg.max_ang, 90, 180);
      cfg.step_deg = constrain(cfg.step_deg, 1, 15);
    }
  }
}

// ------------------------------------------------------------------------------
// SETUP
// ------------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 1200);

  // Pin modes
  pinMode(TRIG_1_PIN, OUTPUT);
  pinMode(ECHO_1_PIN, INPUT);
  digitalWrite(TRIG_1_PIN, LOW);

  pinMode(TRIG_2_PIN, OUTPUT);
  pinMode(ECHO_2_PIN, INPUT); // GPIO 36 is input only
  digitalWrite(TRIG_2_PIN, LOW);

  // Initialize hardware PWM for dual servos
  initServoPWM();

  // Initialize MPU6050 if wired
  initMPU6050();

  // Set initial 90-degree centered stance
  moveServosStaggered(90, 90);
  delay(100);
}

// ------------------------------------------------------------------------------
// MAIN RECONNAISSANCE LOOP
// ------------------------------------------------------------------------------
void loop() {
  // 1. Process laptop instructions
  handleSerialCommands();

  // 2. Compute next target servo positions based on active scan mode
  int target_s1 = cur_s1_ang;
  int target_s2 = cur_s2_ang;

  if (cfg.center_locked) {
    target_s1 = 90;
    target_s2 = 90;
  } else if (cfg.sweep_enabled) {
    switch (cfg.mode) {
      case MODE_STACKED_3D:
        // Both servos step in perfect synchronization across forward cone
        target_s1 += (s1_sweep_dir * cfg.step_deg);
        if (target_s1 >= cfg.max_ang) {
          target_s1 = cfg.max_ang;
          s1_sweep_dir = -1; // Reverse toward right
        } else if (target_s1 <= cfg.min_ang) {
          target_s1 = cfg.min_ang;
          s1_sweep_dir = 1;  // Reverse toward left
        }
        target_s2 = target_s1; // High beam follows low beam angle
        break;

      case MODE_OPPOSED_360:
        // Servo 1 scans Front (0-180); Servo 2 faces opposite Rear (180 - s1)
        target_s1 += (s1_sweep_dir * cfg.step_deg);
        if (target_s1 >= 180) {
          target_s1 = 180;
          s1_sweep_dir = -1;
        } else if (target_s1 <= 0) {
          target_s1 = 0;
          s1_sweep_dir = 1;
        }
        target_s2 = 180 - target_s1; // Opposed backward orientation
        break;

      case MODE_PITCH_TILT_3D:
        // Servo 1 steps Yaw; Servo 2 steps vertical pitch angle
        target_s1 += (s1_sweep_dir * cfg.step_deg);
        if (target_s1 >= cfg.max_ang) {
          target_s1 = cfg.max_ang;
          s1_sweep_dir = -1;
          // Step pitch elevation at each sweep turnaround
          cur_pitch_ang += (pitch_dir * cfg.pitch_step);
          if (cur_pitch_ang >= cfg.pitch_max) {
            cur_pitch_ang = cfg.pitch_max;
            pitch_dir = -1;
          } else if (cur_pitch_ang <= cfg.pitch_min) {
            cur_pitch_ang = cfg.pitch_min;
            pitch_dir = 1;
          }
        } else if (target_s1 <= cfg.min_ang) {
          target_s1 = cfg.min_ang;
          s1_sweep_dir = 1;
        }
        target_s2 = 90 + cur_pitch_ang; // Servo 2 drives pitch elevation
        break;
    }

    // Move servos with anti-brownout delay
    moveServosStaggered(target_s1, target_s2);
  }

  // 3. Sequential Anti-Crosstalk Ultrasonic Firing
  bool valid1 = false;
  bool valid2 = false;

  // Fire Sensor 1 (Low Beam)
  float raw_d1 = fireSingleUltrasonic(TRIG_1_PIN, ECHO_1_PIN, valid1);

  // Delay 12ms to allow acoustic multipath reverberations to completely decay
  delay(12);

  // Fire Sensor 2 (High / Tilted Beam)
  float raw_d2 = fireSingleUltrasonic(TRIG_2_PIN, ECHO_2_PIN, valid2);

  // 4. Rolling 3-Sample Median Filter
  s1_samples[sample_idx] = valid1 ? raw_d1 : 400.0f;
  s2_samples[sample_idx] = valid2 ? raw_d2 : 400.0f;
  sample_idx = (sample_idx + 1) % 3;

  float d1_filtered = median3(s1_samples[0], s1_samples[1], s1_samples[2]);
  float d2_filtered = median3(s2_samples[0], s2_samples[1], s2_samples[2]);

  // Compute 2.5D/3D depth differential Delta d
  float delta_d = d2_filtered - d1_filtered;

  // 5. Tier-1 Deterministic Hardware Safety Stop
  // If either sensor sees a valid obstacle within critical 18.0 cm perimeter, trigger safety stop
  int safety_stop = 0;
  if ((valid1 && d1_filtered < 18.0f) || (valid2 && d2_filtered < 18.0f)) {
    safety_stop = 1;
  }

  // 6. Update IMU if present
  updateIMU();

  // 7. Stream Telemetry JSON Packet (Single source of truth)
  const char* mode_str = "STACKED_3D";
  if (cfg.mode == MODE_OPPOSED_360) mode_str = "OPPOSED_360";
  else if (cfg.mode == MODE_PITCH_TILT_3D) mode_str = "PITCH_TILT_3D";

  Serial.print("{\"bot_id\":\"BUPI-01\",");
  Serial.print("\"ts\":"); Serial.print(millis()); Serial.print(",");
  Serial.print("\"mode\":\""); Serial.print(mode_str); Serial.print("\",");
  Serial.print("\"s1_ang\":"); Serial.print(cur_s1_ang); Serial.print(",");
  Serial.print("\"s2_ang\":"); Serial.print(cur_s2_ang); Serial.print(",");
  Serial.print("\"d1_cm\":"); Serial.print(d1_filtered, 1); Serial.print(",");
  Serial.print("\"d2_cm\":"); Serial.print(d2_filtered, 1); Serial.print(",");
  Serial.print("\"delta_d\":"); Serial.print(delta_d, 1); Serial.print(",");
  Serial.print("\"valid1\":"); Serial.print(valid1 ? 1 : 0); Serial.print(",");
  Serial.print("\"valid2\":"); Serial.print(valid2 ? 1 : 0); Serial.print(",");
  Serial.print("\"safety_stop\":"); Serial.print(safety_stop); Serial.print(",");
  Serial.print("\"imu\":"); Serial.print(imu_detected ? "true" : "false"); Serial.print(",");

  if (imu_detected) {
    Serial.print("\"yaw\":"); Serial.print(estimated_yaw, 1); Serial.print(",");
    Serial.print("\"pitch\":"); Serial.print(estimated_pitch, 1);
  } else {
    Serial.print("\"yaw\":null,\"pitch\":null");
  }
  Serial.println("}");

  // Regulate loop rate (~16 Hz execution)
  delay(18);
}

