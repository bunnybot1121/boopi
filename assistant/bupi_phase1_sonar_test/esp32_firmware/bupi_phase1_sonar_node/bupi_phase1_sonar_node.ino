/*
 * BUPI Autonomous Robotics Fleet — Ultrasonic Hardware Servo Turret Firmware
 * Sketch: bupi_sonar_vision_node.ino
 * Path: bupi_phase1_sonar_test/esp32_firmware/bupi_phase1_sonar_node/bupi_phase1_sonar_node.ino
 *
 * Hardware Peripherals:
 *   - 1x ESP32 Dev Module
 *   - 1x Servo Motor (SG90 / MG90S / MG996R) on GPIO 13 (50 Hz LEDC PWM)
 *   - 1x HC-SR04 Ultrasonic Sensor on TRIG=GPIO 5, ECHO=GPIO 18
 *   - Optional MPU-6050 6-Axis IMU on SDA=GPIO 21, SCL=GPIO 22
 *
 * Telemetry Output: Newline-delimited JSON over USB Serial @ 115200 baud
 * Features: Sub-degree S-curve smoothstep interpolation & soft turnaround deceleration
 */

#include <Wire.h>
#include <math.h>

// --- Pinout Configuration ---
#define SERVO_PIN      13
#define TRIG_PIN       5
#define ECHO_PIN       18
#define I2C_SDA_PIN    21
#define I2C_SCL_PIN    22

// --- Timing & Sensor Limits ---
#define ECHO_TIMEOUT_US     25000       // 25ms timeout (~428 cm max distance, never hangs)
#define CRITICAL_SAFETY_CM  15.0f

// --- MPU-6050 Registers ---
#define MPU_ADDR_PRIMARY    0x68
#define MPU_ADDR_SECONDARY  0x69
#define MPU_REG_PWR_MGMT_1  0x6B
#define MPU_REG_ACCEL_XOUT  0x3B
#define MPU_REG_GYRO_ZOUT   0x47

// --- Universal Core 2.x / 3.x LEDC Servo PWM Abstraction ---
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  #define BUPI_LEDC_V3 1
#else
  #define BUPI_LEDC_V3 0
  #define SERVO_PWM_CHANNEL 0
#endif

// --- Servo Turret State ---
int min_angle = 45;
int max_angle = 135;
int step_deg = 2;
int settle_ms = 10;
float current_angle_f = 90.0f;
int sweep_direction = 1;
bool sweep_enabled = true;
int hold_angle = 90;

// --- IMU Tracking State ---
bool imu_detected = false;
uint8_t mpu_addr = MPU_ADDR_PRIMARY;
float gyro_z_bias = 0.0f;
float current_yaw = 90.0f;
float current_pitch = 0.0f;
unsigned long last_imu_us = 0;

float calculate_median3(float a, float b, float c) {
  if ((a <= b && b <= c) || (c <= b && b <= a)) return b;
  if ((b <= a && a <= c) || (c <= a && a <= b)) return a;
  return c;
}

void init_servo_pwm() {
#if BUPI_LEDC_V3
  ledcAttach(SERVO_PIN, 50, 16);
#else
  ledcSetup(SERVO_PWM_CHANNEL, 50, 16);
  ledcAttachPin(SERVO_PIN, SERVO_PWM_CHANNEL);
#endif
}

void write_servo_angle(float angle_deg) {
  angle_deg = constrain(angle_deg, 0.0f, 180.0f);
  float pulse_us = 500.0f + (angle_deg * 1900.0f) / 180.0f;
  uint32_t duty = (uint32_t)((pulse_us * 65535.0f) / 20000.0f);
#if BUPI_LEDC_V3
  ledcWrite(SERVO_PIN, duty);
#else
  ledcWrite(SERVO_PWM_CHANNEL, duty);
#endif
}

// Quintic smoothstep easing for zero acceleration jerk
float smooth_easing(float t) {
  if (t <= 0.0f) return 0.0f;
  if (t >= 1.0f) return 1.0f;
  return t * t * t * (t * (t * 6.0f - 15.0f) + 10.0f);
}

void move_servo_smooth(float target_ang, int duration_ms) {
  float start_ang = current_angle_f;
  float delta = target_ang - start_ang;
  if (fabsf(delta) < 0.05f) {
    write_servo_angle(target_ang);
    current_angle_f = target_ang;
    return;
  }
  int slices = duration_ms / 5;
  if (slices < 4) slices = 4;
  int slice_ms = duration_ms / slices;
  for (int i = 1; i <= slices; i++) {
    float t = (float)i / (float)slices;
    float ease = smooth_easing(t);
    write_servo_angle(start_ang + delta * ease);
    delay(slice_ms);
  }
  write_servo_angle(target_ang);
  current_angle_f = target_ang;
}

float ping_single(bool &is_valid) {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  unsigned long duration = pulseIn(ECHO_PIN, HIGH, ECHO_TIMEOUT_US);
  if (duration == 0 || duration >= ECHO_TIMEOUT_US) {
    is_valid = false;
    return 400.0f;
  }
  float d = (float)duration * 0.01715f;
  if (d < 2.0f || d > 400.0f) {
    is_valid = false;
    return 400.0f;
  }
  is_valid = true;
  return d;
}

float read_median_distance(bool &is_valid) {
  bool v1, v2, v3;
  float d1 = ping_single(v1);
  delayMicroseconds(400);
  float d2 = ping_single(v2);
  delayMicroseconds(400);
  float d3 = ping_single(v3);
  int valid_count = (v1 ? 1 : 0) + (v2 ? 1 : 0) + (v3 ? 1 : 0);
  is_valid = (valid_count >= 2);
  return calculate_median3(d1, d2, d3);
}

bool detect_mpu(uint8_t &found_addr) {
  Wire.beginTransmission(MPU_ADDR_PRIMARY);
  if (Wire.endTransmission() == 0) {
    found_addr = MPU_ADDR_PRIMARY;
    return true;
  }
  Wire.beginTransmission(MPU_ADDR_SECONDARY);
  if (Wire.endTransmission() == 0) {
    found_addr = MPU_ADDR_SECONDARY;
    return true;
  }
  return false;
}

void init_mpu(uint8_t addr) {
  Wire.beginTransmission(addr);
  Wire.write(MPU_REG_PWR_MGMT_1);
  Wire.write(0x00);
  Wire.endTransmission(true);
  delay(25);

  long accum = 0;
  for (int i = 0; i < 60; i++) {
    Wire.beginTransmission(addr);
    Wire.write(MPU_REG_GYRO_ZOUT);
    Wire.endTransmission(false);
    Wire.requestFrom(addr, (uint8_t)2, (uint8_t)true);
    if (Wire.available() >= 2) {
      int16_t gz = (Wire.read() << 8) | Wire.read();
      accum += gz;
    }
    delay(2);
  }
  gyro_z_bias = (float)accum / 60.0f;
  last_imu_us = micros();
}

void update_imu() {
  if (!imu_detected) return;

  Wire.beginTransmission(mpu_addr);
  Wire.write(MPU_REG_ACCEL_XOUT);
  Wire.endTransmission(false);
  Wire.requestFrom(mpu_addr, (uint8_t)14, (uint8_t)true);

  if (Wire.available() >= 14) {
    int16_t ax = (Wire.read() << 8) | Wire.read();
    int16_t ay = (Wire.read() << 8) | Wire.read();
    int16_t az = (Wire.read() << 8) | Wire.read();
    Wire.read(); Wire.read();
    Wire.read(); Wire.read();
    int16_t gz = (Wire.read() << 8) | Wire.read();

    unsigned long now_us = micros();
    float dt = (now_us - last_imu_us) * 1e-6f;
    last_imu_us = now_us;
    if (dt <= 0.0f || dt > 0.5f) dt = 0.02f;

    float accel_mag = sqrtf((float)ay * ay + (float)az * az);
    if (accel_mag > 0.0f) {
      current_pitch = atan2f(-(float)ax, accel_mag) * 57.29578f;
    }
    float gz_dps = ((float)gz - gyro_z_bias) / 131.0f;
    if (fabsf(gz_dps) > 0.4f) {
      current_yaw += gz_dps * dt;
    }
    while (current_yaw < 0.0f) current_yaw += 360.0f;
    while (current_yaw >= 360.0f) current_yaw -= 360.0f;
  }
}

int extract_json_int(const String &json, const String &key, int default_val) {
  int k_idx = json.indexOf("\"" + key + "\"");
  if (k_idx < 0) return default_val;
  int colon_idx = json.indexOf(':', k_idx);
  if (colon_idx < 0) return default_val;
  int end_idx = json.indexOf(',', colon_idx);
  if (end_idx < 0) end_idx = json.indexOf('}', colon_idx);
  if (end_idx < 0) return default_val;
  String val_str = json.substring(colon_idx + 1, end_idx);
  val_str.trim();
  return val_str.toInt();
}

void process_serial_command() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() < 5) return;

  if (line.indexOf("SERVO_CFG") >= 0) {
    int new_min = extract_json_int(line, "min_ang", min_angle);
    int new_max = extract_json_int(line, "max_ang", max_angle);
    int new_step = extract_json_int(line, "step", step_deg);
    int new_en = extract_json_int(line, "sweep_en", sweep_enabled ? 1 : 0);
    int new_hold = extract_json_int(line, "hold_ang", hold_angle);

    min_angle = constrain(new_min, 0, 180);
    max_angle = constrain(new_max, min_angle, 180);
    step_deg = constrain(new_step, 1, 20);
    sweep_enabled = (new_en == 1);
    hold_angle = constrain(new_hold, 0, 180);

    if (!sweep_enabled) {
      move_servo_smooth((float)hold_angle, 150);
    }
  } else if (line.indexOf("zero_yaw") >= 0) {
    current_yaw = 90.0f;
  }
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 800);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  init_servo_pwm();
  move_servo_smooth(90.0f, 200);
  delay(100);

  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, 400000);
  imu_detected = detect_mpu(mpu_addr);
  if (imu_detected) {
    init_mpu(mpu_addr);
  }
}

void loop() {
  process_serial_command();

  if (sweep_enabled) {
    float dist_min = current_angle_f - (float)min_angle;
    float dist_max = (float)max_angle - current_angle_f;
    float dist_edge = dist_min < dist_max ? dist_min : dist_max;
    if (dist_edge < 0.0f) dist_edge = 0.0f;

    float speed_factor = 1.0f;
    if (dist_edge < 12.0f) {
      speed_factor = 0.40f + 0.60f * (0.5f * (1.0f - cosf((dist_edge / 12.0f) * 3.14159265f)));
    }
    float dyn_step = (float)step_deg * speed_factor;
    if (dyn_step < 0.6f) dyn_step = 0.6f;

    current_angle_f += (float)sweep_direction * dyn_step;
    if (current_angle_f >= (float)max_angle) {
      current_angle_f = (float)max_angle;
      sweep_direction = -1;
    } else if (current_angle_f <= (float)min_angle) {
      current_angle_f = (float)min_angle;
      sweep_direction = 1;
    }
    move_servo_smooth(current_angle_f, 32);
  } else {
    move_servo_smooth((float)hold_angle, 50);
  }

  delay(settle_ms);

  bool is_valid = false;
  float d_cm = read_median_distance(is_valid);

  if (imu_detected) {
    update_imu();
  }

  int safety_stop = (is_valid && d_cm <= CRITICAL_SAFETY_CM) ? 1 : 0;
  unsigned long now = millis();

  Serial.print("{\"bot_id\":\"BUPI-01\",\"ts\":");
  Serial.print(now);
  Serial.print(",\"s_ang\":");
  Serial.print(current_angle_f, 1);
  Serial.print(",\"min_ang\":");
  Serial.print(min_angle);
  Serial.print(",\"max_ang\":");
  Serial.print(max_angle);
  Serial.print(",\"d_cm\":");
  Serial.print(d_cm, 1);
  Serial.print(",\"valid\":");
  Serial.print(is_valid ? 1 : 0);
  Serial.print(",\"safety_stop\":");
  Serial.print(safety_stop);
  Serial.print(",\"imu\":");
  Serial.print(imu_detected ? "true" : "false");
  Serial.print(",\"yaw\":");
  if (imu_detected) Serial.print(current_yaw, 1);
  else Serial.print("null");
  Serial.print(",\"pitch\":");
  if (imu_detected) Serial.print(current_pitch, 1);
  else Serial.print("null");
  Serial.println("}");
}
