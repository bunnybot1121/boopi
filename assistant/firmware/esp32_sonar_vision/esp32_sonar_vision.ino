/*
 * BUPI Autonomous Robotics Fleet — Ultrasonic 2.5D/3D Vision Firmware
 * Sketch: esp32_sonar_vision.ino
 * Path: firmware/esp32_sonar_vision/esp32_sonar_vision.ino
 *
 * Hardware:
 *   - ESP32 Dev Module
 *   - HC-SR04 Ultrasonic Sensor:
 *       TRIG -> GPIO 5
 *       ECHO -> GPIO 18 (via 1k / 2k ohm voltage divider to 3.3V)
 *   - Optional MPU-6050 6-Axis IMU (Raw Wire.h, auto-detected):
 *       SDA  -> GPIO 21
 *       SCL  -> GPIO 22
 *       VCC  -> 3.3V
 *       GND  -> GND
 *
 * Telemetry Output: 16 Hz JSON Lines over Serial @ 115200 baud
 * Format: {"ts":1234,"d_cm":187.9,"valid":1,"safety_stop":0,"imu":false,"yaw":null,"pitch":null}
 */

#include <Wire.h>

// --- Pinout Configuration ---
#define TRIG_PIN 5
#define ECHO_PIN 18
#define I2C_SDA_PIN 21
#define I2C_SCL_PIN 22

// --- Timing & Limits ---
#define ECHO_TIMEOUT_US 25000       // 25ms timeout (~428 cm max distance, loop never hangs)
#define TELEMETRY_INTERVAL_MS 62    // ~16.1 Hz stream
#define MEDIAN_SAMPLES 3
#define CRITICAL_SAFETY_CM 15.0f

// --- MPU-6050 Registers (Raw Wire.h) ---
#define MPU_ADDR_PRIMARY   0x68
#define MPU_ADDR_SECONDARY 0x69
#define MPU_REG_PWR_MGMT_1 0x6B
#define MPU_REG_ACCEL_XOUT 0x3B
#define MPU_REG_GYRO_ZOUT  0x47

// --- Rolling Median Filter State ---
float median_buf[MEDIAN_SAMPLES] = {0.0f, 0.0f, 0.0f};
uint8_t median_idx = 0;
uint8_t median_count = 0;

// --- IMU Tracking State ---
bool imu_detected = false;
uint8_t mpu_addr = MPU_ADDR_PRIMARY;
float gyro_z_bias = 0.0f;
float current_yaw = 90.0f;   // Default 90 deg = straight ahead
float current_pitch = 0.0f;
unsigned long last_imu_us = 0;

// --- Loop Timing ---
unsigned long last_telemetry_ms = 0;

// 3-sample median computation
float calculate_median3(float a, float b, float c) {
  if ((a <= b && b <= c) || (c <= b && b <= a)) return b;
  if ((b <= a && a <= c) || (c <= a && a <= b)) return a;
  return c;
}

// Probe I2C for MPU6050
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

// Initialize MPU6050 and calibrate gyro Z
void init_mpu(uint8_t addr) {
  Wire.beginTransmission(addr);
  Wire.write(MPU_REG_PWR_MGMT_1);
  Wire.write(0x00); // Wake up device
  Wire.endTransmission(true);
  delay(25);

  // Calibrate Gyro Z resting bias over 100 samples
  long accum = 0;
  for (int i = 0; i < 100; i++) {
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
  gyro_z_bias = (float)accum / 100.0f;
  last_imu_us = micros();
}

// Read IMU Pitch & Yaw
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
    Wire.read(); Wire.read(); // Skip temp
    Wire.read(); Wire.read(); // Skip gyro X
    Wire.read(); Wire.read(); // Skip gyro Y
    int16_t gz = (Wire.read() << 8) | Wire.read();

    unsigned long now_us = micros();
    float dt = (now_us - last_imu_us) * 1e-6f;
    last_imu_us = now_us;
    if (dt <= 0.0f || dt > 0.5f) dt = 0.02f;

    // Pitch from Accelerometer
    float accel_mag = sqrtf((float)ay * ay + (float)az * az);
    if (accel_mag > 0.0f) {
      current_pitch = atan2f(-(float)ax, accel_mag) * 57.29578f;
    }

    // Yaw integration from Gyro Z (131.0 LSB/dps at +-250 dps)
    float gz_dps = ((float)gz - gyro_z_bias) / 131.0f;
    if (fabsf(gz_dps) > 0.4f) { // Noise deadband
      current_yaw += gz_dps * dt;
    }

    // Keep yaw normalized between 0 and 180 degrees forward sector
    if (current_yaw < 0.0f) current_yaw = 0.0f;
    if (current_yaw > 180.0f) current_yaw = 180.0f;
  }
}

// Non-blocking HC-SR04 ping with 25ms timeout
float read_sonar_cm(bool &is_valid) {
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

  // Speed of sound = 343 m/s -> 0.01715 cm/us
  float d = (float)duration * 0.01715f;
  if (d < 2.0f || d > 400.0f) {
    is_valid = false;
    return 400.0f;
  }

  is_valid = true;
  return d;
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 800);

  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  // Auto-detect I2C MPU-6050
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, 400000);
  imu_detected = detect_mpu(mpu_addr);
  if (imu_detected) {
    init_mpu(mpu_addr);
  }

  last_telemetry_ms = millis();
}

void loop() {
  unsigned long now = millis();

  // Read incoming serial commands
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd.indexOf("zero_yaw") >= 0) {
      current_yaw = 90.0f; // Center forward
    }
  }

  // Dispatch Telemetry at ~16 Hz
  if (now - last_telemetry_ms >= TELEMETRY_INTERVAL_MS) {
    last_telemetry_ms = now;

    bool ping_valid = false;
    float raw_cm = read_sonar_cm(ping_valid);

    // Rolling 3-sample median filter
    median_buf[median_idx] = raw_cm;
    median_idx = (median_idx + 1) % MEDIAN_SAMPLES;
    if (median_count < MEDIAN_SAMPLES) median_count++;

    float filtered_cm = raw_cm;
    if (median_count >= 3) {
      filtered_cm = calculate_median3(median_buf[0], median_buf[1], median_buf[2]);
    }

    if (imu_detected) {
      update_imu();
    }

    int safety_stop = (ping_valid && filtered_cm <= CRITICAL_SAFETY_CM) ? 1 : 0;

    // Strict JSON line matching project specification
    Serial.print("{\"ts\":");
    Serial.print(now);
    Serial.print(",\"d_cm\":");
    Serial.print(filtered_cm, 1);
    Serial.print(",\"valid\":");
    Serial.print(ping_valid ? 1 : 0);
    Serial.print(",\"safety_stop\":");
    Serial.print(safety_stop);
    Serial.print(",\"imu\":");
    Serial.print(imu_detected ? "true" : "false");
    Serial.print(",\"yaw\":");
    if (imu_detected) {
      Serial.print(current_yaw, 1);
    } else {
      Serial.print("null");
    }
    Serial.print(",\"pitch\":");
    if (imu_detected) {
      Serial.print(current_pitch, 1);
    } else {
      Serial.print("null");
    }
    Serial.println("}");
  }
}

