/*
 * ==============================================================================
 * BUPI DUAL-ULTRASONIC + DUAL-SERVO 2.5D/3D SPATIAL SCANNER FIRMWARE
 * Smooth S-Curve Motion & Micro-Stepped Turret Sweeping
 * Project: BUPI Autonomous Robotics Fleet
 * Target: ESP32 Microcontroller (Zero External Library Conflicts)
 *
 * HARDWARE PINOUT:
 *   - Sensor 1 (Low / Primary Beam):  TRIG_1 = GPIO 5,  ECHO_1 = GPIO 18 (Voltage Shifted)
 *   - Sensor 2 (High / Tilted Beam):   TRIG_2 = GPIO 19, ECHO_2 = GPIO 23 (D23 on silkscreen)
 *   - Servo 1 (Azimuth / Yaw 1):       GPIO 13 (50 Hz Hardware PWM)
 *   - Servo 2 (Elevation / Yaw 2):     GPIO 16 (50 Hz Hardware PWM)
 *   - MPU6050 IMU (Optional Auto-ID): SDA = GPIO 21,  SCL = GPIO 22 (0x68 / 0x69)
 *
 * SMOOTH MOTION FEATURES:
 *   1. Sub-Degree Micro-Resolution via 14-Bit LEDC PWM (0.11 deg step precision).
 *   2. Quintic Smoothstep Hermite S-Curve Easing: S(t) = 6t^5 - 15t^4 + 10t^3.
 *   3. Soft Boundary Deceleration: Cosine easing when approaching min/max sector bounds.
 *   4. Anti-Brownout Staggered Micro-Slices (2ms gap between servo PWM writes).
 *   5. Anti-Crosstalk Acoustic Gap (12ms decay between dual ping bursts).
 * ==============================================================================
 */

#include <Arduino.h>
#include <Wire.h>
#include <math.h>

// --- Hardware Pin Definitions ---
#define TRIG_1_PIN     5
#define ECHO_1_PIN     18
#define TRIG_2_PIN     19
#define ECHO_2_PIN     23    // GPIO 23 (D23)
#define SERVO_1_PIN    13
#define SERVO_2_PIN    16
#define I2C_SDA_PIN    21
#define I2C_SCL_PIN    22

// --- Servo PWM Setup (50 Hz, 14-bit resolution, 500us to 2400us) ---
#define SERVO_PWM_FREQ       50
#define SERVO_PWM_RES        14     // 0 to 16383
#define SERVO_MIN_US         500
#define SERVO_MAX_US         2400
#define SERVO_PERIOD_US      20000

enum ScanMode {
  MODE_STACKED_3D = 0,
  MODE_OPPOSED_360 = 1,
  MODE_PITCH_TILT_3D = 2
};

struct ScanConfig {
  ScanMode mode        = MODE_STACKED_3D;
  float min_ang        = 45.0f;
  float max_ang        = 135.0f;
  float step_deg       = 2.0f;
  int settle_ms        = 25;  // 25ms mechanical servo horn stabilization
  int move_ms          = 35;
  bool sweep_enabled   = true;
  bool center_locked   = false;
  float pitch_min      = 0.0f;
  float pitch_max      = 30.0f;
  float pitch_step     = 5.0f;
} cfg;

#define SERVO_HORN_OFFSET_CM 3.5f  // Distance from servo rotation pivot to transducer face

// Turret runtime positions (float for sub-degree smooth motion)
float cur_s1_ang = 90.0f;
float cur_s2_ang = 90.0f;
float cur_pitch_ang = 10.0f;
int s1_sweep_dir = 1;
int pitch_dir = 1;

// IMU State
bool imu_detected = false;
uint8_t imu_addr = 0x68;
float gyro_z_bias = 0.0f, gyro_y_bias = 0.0f;
float est_yaw = 0.0f, est_pitch = 0.0f;
unsigned long last_imu_us = 0;

// Rolling buffers for 3-sample median filter
float s1_hist[3] = {400.0f, 400.0f, 400.0f};
float s2_hist[3] = {400.0f, 400.0f, 400.0f};
uint8_t hist_idx = 0;

// --- Sub-degree High-Resolution LEDC Servo Driver ---
uint32_t angleToDuty(float angle_deg) {
  angle_deg = constrain(angle_deg, 0.0f, 180.0f);
  float pulse_us = (float)SERVO_MIN_US + ((float)(SERVO_MAX_US - SERVO_MIN_US) * angle_deg / 180.0f);
  return (uint32_t)((pulse_us * ((1 << SERVO_PWM_RES) - 1)) / (float)SERVO_PERIOD_US);
}

void initServoPWM() {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  ledcAttach(SERVO_1_PIN, SERVO_PWM_FREQ, SERVO_PWM_RES);
  ledcAttach(SERVO_2_PIN, SERVO_PWM_FREQ, SERVO_PWM_RES);
#else
  ledcSetup(0, SERVO_PWM_FREQ, SERVO_PWM_RES);
  ledcAttachPin(SERVO_1_PIN, 0);
  ledcSetup(1, SERVO_PWM_FREQ, SERVO_PWM_RES);
  ledcAttachPin(SERVO_2_PIN, 1);
#endif
}

void writeRawServo1(float angle_deg) {
  uint32_t duty = angleToDuty(angle_deg);
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  ledcWrite(SERVO_1_PIN, duty);
#else
  ledcWrite(0, duty);
#endif
  cur_s1_ang = angle_deg;
}

void writeRawServo2(float angle_deg) {
  uint32_t duty = angleToDuty(angle_deg);
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  ledcWrite(SERVO_2_PIN, duty);
#else
  ledcWrite(1, duty);
#endif
  cur_s2_ang = angle_deg;
}

// Quintic Smoothstep Easing: S(t) = 6t^5 - 15t^4 + 10t^3 (zero jerk at endpoints)
float smoothEasing(float t) {
  if (t <= 0.0f) return 0.0f;
  if (t >= 1.0f) return 1.0f;
  return t * t * t * (t * (t * 6.0f - 15.0f) + 10.0f);
}

// Micro-stepped S-curve movement: translates abrupt jumps into smooth glides
void moveServosSmooth(float target_s1, float target_s2, int duration_ms) {
  float start_s1 = cur_s1_ang;
  float start_s2 = cur_s2_ang;
  float delta_1 = target_s1 - start_s1;
  float delta_2 = target_s2 - start_s2;

  if (fabs(delta_1) < 0.05f && fabs(delta_2) < 0.05f) {
    writeRawServo1(target_s1);
    writeRawServo2(target_s2);
    return;
  }

  int slices = duration_ms / 6;
  if (slices < 4) slices = 4;
  int slice_delay = duration_ms / slices;

  for (int i = 1; i <= slices; i++) {
    float t = (float)i / (float)slices;
    float ease = smoothEasing(t);
    writeRawServo1(start_s1 + delta_1 * ease);
    delay(2); // Stagger PWM updates to prevent simultaneous motor coil inrush
    writeRawServo2(start_s2 + delta_2 * ease);
    if (slice_delay > 2) delay(slice_delay - 2);
  }
  writeRawServo1(target_s1);
  writeRawServo2(target_s2);
  delay(cfg.settle_ms);
}

// --- HC-SR04 Ultrasonic Transducer Driver (Calibrated at 24°C + Servo Pivot Offset) ---
float fireSingleUltrasonic(uint8_t trig_pin, uint8_t echo_pin, bool &is_valid) {
  for (int attempt = 0; attempt < 2; attempt++) {
    digitalWrite(trig_pin, LOW);
    delayMicroseconds(4);
    digitalWrite(trig_pin, HIGH);
    delayMicroseconds(10);
    digitalWrite(trig_pin, LOW);

    unsigned long duration_us = pulseIn(echo_pin, HIGH, 25000UL);
    if (duration_us > 115) { // Minimum ~2cm
      // Speed of sound at 24°C: 345.8 m/s -> 0.03458 cm/us / 2 = 0.01729 cm/us
      float dist_cm = ((float)duration_us * 0.01729f) + SERVO_HORN_OFFSET_CM;
      if (dist_cm >= 2.0f && dist_cm <= 400.0f) {
        is_valid = true;
        return dist_cm;
      }
    }
    delayMicroseconds(500);
  }
  is_valid = false;
  return 400.0f;
}

float median3(float a, float b, float c) {
  if ((a <= b && b <= c) || (c <= b && b <= a)) return b;
  if ((b <= a && a <= c) || (c <= a && a <= b)) return a;
  return c;
}

// --- MPU6050 Raw I2C Driver ---
bool checkI2C(uint8_t addr) {
  Wire.beginTransmission(addr);
  return (Wire.endTransmission() == 0);
}

void initMPU6050() {
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, 400000UL);
  if (checkI2C(0x68)) imu_addr = 0x68;
  else if (checkI2C(0x69)) imu_addr = 0x69;
  else { imu_detected = false; return; }

  imu_detected = true;
  Wire.beginTransmission(imu_addr);
  Wire.write(0x6B); // PWR_MGMT_1
  Wire.write(0x00); // Wake
  Wire.endTransmission();
  delay(15);

  float sum_z = 0.0f, sum_y = 0.0f;
  for (int i = 0; i < 40; i++) {
    Wire.beginTransmission(imu_addr);
    Wire.write(0x45); // GYRO_YOUT_H
    Wire.endTransmission(false);
    Wire.requestFrom(imu_addr, (uint8_t)4);
    if (Wire.available() >= 4) {
      int16_t gy = (Wire.read() << 8) | Wire.read();
      int16_t gz = (Wire.read() << 8) | Wire.read();
      sum_y += (float)gy / 131.0f;
      sum_z += (float)gz / 131.0f;
    }
    delay(3);
  }
  gyro_y_bias = sum_y / 40.0f;
  gyro_z_bias = sum_z / 40.0f;
  last_imu_us = micros();
}

void updateIMU() {
  if (!imu_detected) return;
  unsigned long now_us = micros();
  float dt = (float)(now_us - last_imu_us) / 1000000.0f;
  last_imu_us = now_us;
  if (dt <= 0.0f || dt > 0.5f) dt = 0.02f;

  Wire.beginTransmission(imu_addr);
  Wire.write(0x45);
  Wire.endTransmission(false);
  Wire.requestFrom(imu_addr, (uint8_t)4);
  if (Wire.available() >= 4) {
    int16_t gy = (Wire.read() << 8) | Wire.read();
    int16_t gz = (Wire.read() << 8) | Wire.read();
    float ry = ((float)gy / 131.0f) - gyro_y_bias;
    float rz = ((float)gz / 131.0f) - gyro_z_bias;
    if (fabs(ry) > 0.8f) est_pitch += ry * dt;
    if (fabs(rz) > 0.8f) est_yaw += rz * dt;
  }
}

// --- Serial JSON Configuration Command Parser ---
void handleSerialCommands() {
  while (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0 || line.charAt(0) != '{') continue;

    if (line.indexOf("\"center_90\":1") != -1 || line.indexOf("\"center\":true") != -1) {
      cfg.center_locked = true;
      cfg.sweep_enabled = false;
      moveServosSmooth(90.0f, 90.0f, 250);
      continue;
    }
    if (line.indexOf("\"center_90\":0") != -1 || line.indexOf("\"resume\":true") != -1) {
      cfg.center_locked = false;
      cfg.sweep_enabled = true;
    }

    if (line.indexOf("\"mode\":\"STACKED_3D\"") != -1) cfg.mode = MODE_STACKED_3D;
    else if (line.indexOf("\"mode\":\"OPPOSED_360\"") != -1) cfg.mode = MODE_OPPOSED_360;
    else if (line.indexOf("\"mode\":\"PITCH_TILT_3D\"") != -1) cfg.mode = MODE_PITCH_TILT_3D;

    int idx_min = line.indexOf("\"min_ang\":");
    if (idx_min != -1) cfg.min_ang = constrain((float)line.substring(idx_min + 10).toFloat(), 0.0f, 90.0f);

    int idx_max = line.indexOf("\"max_ang\":");
    if (idx_max != -1) cfg.max_ang = constrain((float)line.substring(idx_max + 10).toFloat(), 90.0f, 180.0f);

    int idx_step = line.indexOf("\"step\":");
    if (idx_step != -1) cfg.step_deg = constrain((float)line.substring(idx_step + 7).toFloat(), 0.5f, 10.0f);

    int idx_en = line.indexOf("\"sweep_en\":");
    if (idx_en != -1) {
      cfg.sweep_enabled = (line.substring(idx_en + 11).toInt() == 1);
      if (cfg.sweep_enabled) {
        cfg.center_locked = false;
      }
    }
  }
}

// --- Setup ---
void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 1200);

  pinMode(TRIG_1_PIN, OUTPUT);
  pinMode(ECHO_1_PIN, INPUT);
  digitalWrite(TRIG_1_PIN, LOW);

  pinMode(TRIG_2_PIN, OUTPUT);
  pinMode(ECHO_2_PIN, INPUT);
  digitalWrite(TRIG_2_PIN, LOW);

  initServoPWM();
  initMPU6050();

  // Smoothly center servos to 90 degrees on startup
  moveServosSmooth(90.0f, 90.0f, 200);
  delay(100);
}

// --- Main Operational Loop ---
void loop() {
  // 1. Process host commands
  handleSerialCommands();

  // 2. Compute next target servo positions with soft boundary deceleration
  float target_s1 = cur_s1_ang;
  float target_s2 = cur_s2_ang;

  if (cfg.center_locked) {
    if (fabs(cur_s1_ang - 90.0f) > 0.5f || fabs(cur_s2_ang - 90.0f) > 0.5f) {
      moveServosSmooth(90.0f, 90.0f, 200);
    }
  } else if (cfg.sweep_enabled) {
    float dist_min = cur_s1_ang - cfg.min_ang;
    float dist_max = cfg.max_ang - cur_s1_ang;
    float dist_edge = dist_min < dist_max ? dist_min : dist_max;
    if (dist_edge < 0.0f) dist_edge = 0.0f;

    // Harmonic cosine ease-in/ease-out within 12 degrees of sector boundaries
    float speed_factor = 1.0f;
    if (dist_edge < 12.0f) {
      speed_factor = 0.40f + 0.60f * (0.5f * (1.0f - cosf((dist_edge / 12.0f) * 3.14159265f)));
    }
    float dynamic_step = cfg.step_deg * speed_factor;
    if (dynamic_step < 0.6f) dynamic_step = 0.6f;

    switch (cfg.mode) {
      case MODE_STACKED_3D:
        target_s1 += ((float)s1_sweep_dir * dynamic_step);
        if (target_s1 >= cfg.max_ang) {
          target_s1 = cfg.max_ang;
          s1_sweep_dir = -1;
        } else if (target_s1 <= cfg.min_ang) {
          target_s1 = cfg.min_ang;
          s1_sweep_dir = 1;
        }
        target_s2 = target_s1;
        break;

      case MODE_OPPOSED_360:
        target_s1 += ((float)s1_sweep_dir * dynamic_step);
        if (target_s1 >= 180.0f) {
          target_s1 = 180.0f;
          s1_sweep_dir = -1;
        } else if (target_s1 <= 0.0f) {
          target_s1 = 0.0f;
          s1_sweep_dir = 1;
        }
        target_s2 = 180.0f - target_s1;
        break;

      case MODE_PITCH_TILT_3D:
        target_s1 += ((float)s1_sweep_dir * dynamic_step);
        if (target_s1 >= cfg.max_ang) {
          target_s1 = cfg.max_ang;
          s1_sweep_dir = -1;
          cur_pitch_ang += ((float)pitch_dir * cfg.pitch_step);
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
        target_s2 = 90.0f + cur_pitch_ang;
        break;
    }

    moveServosSmooth(target_s1, target_s2, cfg.move_ms);
  }

  // 3. Staggered Anti-Crosstalk Ultrasonic Transducer Pings
  bool valid1 = false, valid2 = false;
  float raw_d1 = fireSingleUltrasonic(TRIG_1_PIN, ECHO_1_PIN, valid1);
  delay(28); // Generous 28ms acoustic reverberation decay gap to prevent crosstalk into Sensor 2
  float raw_d2 = fireSingleUltrasonic(TRIG_2_PIN, ECHO_2_PIN, valid2);

  // 4. Instant Angle-True Filter (Zero multi-angle smearing / zero angular lag)
  float d1_filt = valid1 ? raw_d1 : 400.0f;
  float d2_filt = valid2 ? raw_d2 : 400.0f;
  float delta_d = d2_filt - d1_filt;

  // 5. Tier-1 Hardware Safety Stop (<18.0cm on either sensor)
  int safety_stop = 0;
  if ((valid1 && d1_filt < 18.0f) || (valid2 && d2_filt < 18.0f)) {
    safety_stop = 1;
  }

  updateIMU();

  // 6. JSON Telemetry Stream
  const char* m_str = "STACKED_3D";
  if (cfg.mode == MODE_OPPOSED_360) m_str = "OPPOSED_360";
  else if (cfg.mode == MODE_PITCH_TILT_3D) m_str = "PITCH_TILT_3D";

  Serial.print("{\"bot_id\":\"BUPI-01\",");
  Serial.print("\"ts\":"); Serial.print(millis()); Serial.print(",");
  Serial.print("\"mode\":\""); Serial.print(m_str); Serial.print("\",");
  Serial.print("\"s1_ang\":"); Serial.print(cur_s1_ang, 1); Serial.print(",");
  Serial.print("\"s2_ang\":"); Serial.print(cur_s2_ang, 1); Serial.print(",");
  Serial.print("\"d1_cm\":"); Serial.print(d1_filt, 1); Serial.print(",");
  Serial.print("\"d2_cm\":"); Serial.print(d2_filt, 1); Serial.print(",");
  Serial.print("\"delta_d\":"); Serial.print(delta_d, 1); Serial.print(",");
  Serial.print("\"valid1\":"); Serial.print(valid1 ? 1 : 0); Serial.print(",");
  Serial.print("\"valid2\":"); Serial.print(valid2 ? 1 : 0); Serial.print(",");
  Serial.print("\"safety_stop\":"); Serial.print(safety_stop); Serial.print(",");
  Serial.print("\"imu\":"); Serial.print(imu_detected ? "true" : "false"); Serial.print(",");

  if (imu_detected) {
    Serial.print("\"yaw\":"); Serial.print(est_yaw, 1); Serial.print(",");
    Serial.print("\"pitch\":"); Serial.print(est_pitch, 1);
  } else {
    Serial.print("\"yaw\":null,\"pitch\":null");
  }
  Serial.println("}");
}
