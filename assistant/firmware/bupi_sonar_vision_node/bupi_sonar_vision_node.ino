/*
 * BUPI Autonomous Robotics Fleet — Ultrasonic Hardware Servo Turret Firmware
 * Sketch: bupi_sonar_vision_node.ino
 * Path: firmware/bupi_sonar_vision_node/bupi_sonar_vision_node.ino
 *
 * Hardware Peripherals:
 *   - 1x ESP32 Dev Module
 *   - 1x Servo Motor (SG90 / MG90S / MG996R):
 *       SIGNAL -> GPIO 13 (50 Hz PWM via portable ledc abstraction)
 *       VCC    -> 5V / VIN (or external 5V 1A BEC)
 *       GND    -> Common GND
 *   - 1x HC-SR04 Ultrasonic Sensor (Mounted on Servo Horn):
 *       TRIG   -> GPIO 5
 *       ECHO   -> GPIO 18 (via 1k / 2k voltage divider or direct to 3.3V GPIO)
 *       VCC    -> 5V / VIN (MUST be 5V for transducer oscillation)
 *       GND    -> Common GND
 *   - Optional MPU-6050 6-Axis IMU (Raw Wire.h, auto-detected):
 *       SDA    -> GPIO 21
 *       SCL    -> GPIO 22
 *
 * Telemetry Output: Newline-delimited JSON over USB Serial @ 115200 baud
 * Format:
 *   {"bot_id":"BUPI-01","ts":12450,"s_ang":75,"min_ang":45,"max_ang":135,"d_cm":114.2,"valid":1,"safety_stop":0,"imu":false,"yaw":null,"pitch":null}
 *
 * Two-Way Serial Configuration Input:
 *   {"cmd":"SERVO_CFG","min_ang":60,"max_ang":120,"step":3,"sweep_en":1,"hold_ang":90}
 */

#include <Wire.h>

// --- Pinout Configuration ---
#define SERVO_PIN      13
#define TRIG_PIN       5
#define ECHO_PIN       18
#define I2C_SDA_PIN    21
#define I2C_SCL_PIN    22

// --- Timing & Sensor Limits ---
#define ECHO_TIMEOUT_US     25000       // 25ms timeout (~428 cm max distance, never hangs)
#define CRITICAL_SAFETY_CM  15.0f

// --- MPU-6050 Registers (Raw Wire.h, Zero External Libraries) ---
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
int min_angle = 45;         // Default forward-right sector
int max_angle = 135;        // Default forward-left sector
int step_deg = 3;           // 3-degree angular step
int settle_ms = 30;         // Settle time for mechanical stabilization
int current_angle = 90;     // Start centered straight ahead
int sweep_direction = 1;    // +1 = sweeping right-to-left, -1 = left-to-right
bool sweep_enabled = true;  // Continuous sweep or fixed angle hold
int hold_angle = 90;

// --- IMU Tracking State ---
bool imu_detected = false;
uint8_t mpu_addr = MPU_ADDR_PRIMARY;
float gyro_z_bias = 0.0f;
float current_yaw = 90.0f;
float current_pitch = 0.0f;
unsigned long last_imu_us = 0;

// --- 3-Sample Median Filter ---
float calculate_median3(float a, float b, float c) {
  if ((a <= b && b <= c) || (c <= b && b <= a)) return b;
  if ((b <= a && a <= c) || (c <= a && a <= b)) return a;
  return c;
}

// Universal zero-conflict servo PWM initialization
void init_servo_pwm() {
#if BUPI_LEDC_V3
  ledcAttach(SERVO_PIN, 50, 16);
#else
  ledcSetup(SERVO_PWM_CHANNEL, 50, 16);
  ledcAttachPin(SERVO_PIN, SERVO_PWM_CHANNEL);
#endif
}

// Drive servo to exact angle (0..180 deg) using 500..2400 us pulse width
void write_servo_angle(int angle_deg) {
  angle_deg = constrain(angle_deg, 0, 180);
  // Map 0..180 deg to 500..2400 us pulse
  uint32_t pulse_us = 500 + ((uint32_t)angle_deg * 1900UL) / 180UL;
  // 16-bit resolution duty on 20000 us (50 Hz) period: duty = (pulse_us * 65535) / 20000
  uint32_t duty = (pulse_us * 65535UL) / 20000UL;
#if BUPI_LEDC_V3
  ledcWrite(SERVO_PIN, duty);
#else
  ledcWrite(SERVO_PWM_CHANNEL, duty);
#endif
}

// Non-blocking single HC-SR04 ping with 25ms timeout
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

// 3-Sample Rapid Median Ultrasonic Scan
float read_median_distance(bool &is_valid) {
  bool v1, v2, v3;
  float d1 = ping_single(v1);
  delayMicroseconds(400);
  float d2 = ping_single(v2);
  delayMicroseconds(400);
  float d3 = ping_single(v3);

  // Valid if at least 2 of 3 readings captured an echo
  int valid_count = (v1 ? 1 : 0) + (v2 ? 1 : 0) + (v3 ? 1 : 0);
  is_valid = (valid_count >= 2);

  return calculate_median3(d1, d2, d3);
}

// Probe I2C for MPU-6050
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

// Initialize MPU-6050 and calibrate resting gyro Z
void init_mpu(uint8_t addr) {
  Wire.beginTransmission(addr);
  Wire.write(MPU_REG_PWR_MGMT_1);
  Wire.write(0x00); // Wake up device
  Wire.endTransmission(true);
  delay(25);

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

// Update IMU Pitch & Yaw
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

    // Yaw integration from Gyro Z
    float gz_dps = ((float)gz - gyro_z_bias) / 131.0f;
    if (fabsf(gz_dps) > 0.4f) {
      current_yaw += gz_dps * dt;
    }
    while (current_yaw < 0.0f) current_yaw += 360.0f;
    while (current_yaw >= 360.0f) current_yaw -= 360.0f;
  }
}

// Simple fast key-value extractor for JSON commands without external library dependencies
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

// Process incoming Laptop UI serial commands
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
      current_angle = hold_angle;
      write_servo_angle(current_angle);
    }
  } else if (line.indexOf("zero_yaw") >= 0) {
    current_yaw = 90.0f;
  }
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 800);

  // Initialize HC-SR04 Pins
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  // Initialize Servo PWM on GPIO 13
  init_servo_pwm();
  write_servo_angle(current_angle);
  delay(150);

  // Probe Optional I2C MPU-6050
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, 400000);
  imu_detected = detect_mpu(mpu_addr);
  if (imu_detected) {
    init_mpu(mpu_addr);
  }
}

void loop() {
  // 1. Check for incoming Laptop commands
  process_serial_command();

  // 2. Step Servo Position
  if (sweep_enabled) {
    current_angle += sweep_direction * step_deg;
    if (current_angle >= max_angle) {
      current_angle = max_angle;
      sweep_direction = -1; // Reverse toward right
    } else if (current_angle <= min_angle) {
      current_angle = min_angle;
      sweep_direction = 1;  // Reverse toward left
    }
    write_servo_angle(current_angle);
  } else {
    current_angle = hold_angle;
    write_servo_angle(current_angle);
  }

  // 3. Mechanical Settle Delay
  delay(settle_ms);

  // 4. Fire Rapid 3-Sample Median Ping
  bool is_valid = false;
  float d_cm = read_median_distance(is_valid);

  // 5. Update IMU if present
  if (imu_detected) {
    update_imu();
  }

  int safety_stop = (is_valid && d_cm <= CRITICAL_SAFETY_CM) ? 1 : 0;
  unsigned long now = millis();

  // 6. Stream JSON Telemetry Packet with Hardware Servo Angle "s_ang"
  Serial.print("{\"bot_id\":\"BUPI-01\",\"ts\":");
  Serial.print(now);
  Serial.print(",\"s_ang\":");
  Serial.print(current_angle);
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
