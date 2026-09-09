# BUPI Autonomous Mobile Robot: Master Hardware & Subsystem Specification

## 1. Executive Summary & Hardware Architecture
BUPI is a small differential-drive autonomous mobile robot powered by an **ESP32-WROOM-32** microcontroller.
It integrates real-time sensing, closed-loop actuation, dynamic natural language mission decomposition, and hardware-level safety supervisors.

### Core Hardware Components:
1. **Microcontroller**: ESP32 Dev Module (Dual-core Xtensa 32-bit LX6 @ 240MHz, 520KB SRAM, 4MB Flash).
2. **Motors & Actuators**: Dual N20 Micro Metal Gear DC Motors in differential drive setup with TB6612FNG Dual MOSFET H-Bridge driver.
3. **Inertial Measurement**: MPU6050 6-Axis IMU (3-axis Gyroscope + 3-axis Accelerometer on I2C `0x68`).
4. **Distance Ranging**: HC-SR04 Ultrasonic Distance Sensor ($2\text{ cm} \le d \le 400\text{ cm}$).
5. **Thermal Motion Sensing**: Pyroelectric Passive Infrared (PIR) Motion Sensor (100° FOV, 2.5m range).

---

## 2. Complete ESP32 GPIO Pinout Table

| Hardware Module | Pin Function | ESP32 GPIO | Direction / Type | Electrical Notes |
|---|---|---|---|---|
| **TB6612FNG** | PWMA | `GPIO 25` | Output (LEDC PWM) | Left Motor speed (0–255, 1kHz 8-bit PWM) |
| **TB6612FNG** | AIN1 | `GPIO 26` | Output (Digital) | Left Motor forward direction logic |
| **TB6612FNG** | AIN2 | `GPIO 27` | Output (Digital) | Left Motor reverse direction logic |
| **TB6612FNG** | PWMB | `GPIO 14` | Output (LEDC PWM) | Right Motor speed (0–255, 1kHz 8-bit PWM) |
| **TB6612FNG** | BIN1 | `GPIO 33` | Output (Digital) | Right Motor forward direction logic (**GPIO 33, NOT 32**) |
| **TB6612FNG** | BIN2 | `GPIO 32` | Output (Digital) | Right Motor reverse direction logic |
| **TB6612FNG** | STBY | `GPIO 4` | Output (Digital) | Driver Standby. **Must be pulled HIGH** to enable outputs |
| **HC-SR04** | TRIG | `GPIO 5` | Output (Digital) | 10µs ultrasonic trigger pulse |
| **HC-SR04** | ECHO | `GPIO 18` | Input (Digital) | 5V-to-3.3V resistor divider (1kΩ / 2kΩ) required |
| **PIR Sensor** | OUT | `GPIO 19` | Input (Digital) | Active `HIGH` on thermal infrared flux |
| **MPU6050** | SDA | `GPIO 21` | I2C Data | 400kHz Fast I2C bus (Address `0x68`) |
| **MPU6050** | SCL | `GPIO 22` | I2C Clock | 400kHz Fast I2C bus (Address `0x68`) |
| **Power (VM)** | Motor VM | External | Battery Supply | 3.7V–6V battery pack (never power motors from ESP32 3.3V) |
| **Power (VCC)**| Logic VCC | ESP32 3.3V | Logic Supply | Common ground tied between battery and ESP32 GND |

---

## 3. Direction & Actuation Truth Table

| Motion Intent | Left Motor (AIN1, AIN2) | Right Motor (BIN1, BIN2) | STBY | Left PWM | Right PWM |
|---|---|---|---|---|---|
| **MOVE_FORWARD** | `HIGH`, `LOW` | `HIGH`, `LOW` | `HIGH` | Nominal (180–220) | Nominal (180–220) |
| **MOVE_BACKWARD** | `LOW`, `HIGH` | `LOW`, `HIGH` | `HIGH` | Nominal (180–220) | Nominal (180–220) |
| **TURN_LEFT** | `LOW`, `HIGH` (reverse) | `HIGH`, `LOW` (forward) | `HIGH` | Turn PWM (160–180) | Turn PWM (160–180) |
| **TURN_RIGHT** | `HIGH`, `LOW` (forward) | `LOW`, `HIGH` (reverse) | `HIGH` | Turn PWM (160–180) | Turn PWM (160–180) |
| **STOP / BRAKE** | `LOW`, `LOW` | `LOW`, `LOW` | `HIGH` | 0 | 0 |
| **STANDBY OFF** | Any | Any | `LOW` | 0 | 0 |

---

## 4. Epistemic Sensor Fusion & Perception Ladder

BUPI strictly adheres to epistemic honesty to prevent false perception:
1. **PIR Alone**:
   - Only proves thermal infrared motion flux across optical zones.
   - Classification: `THERMAL_FLUX_DETECTED` or `POSSIBLE_WARM_MOVING_TARGET`.
   - Prohibited assertion: Never claim "human confirmed" or "person identified".
2. **Ultrasonic HC-SR04 Alone**:
   - Measures acoustic time-of-flight distance.
   - Prohibited assertion: Cannot differentiate a person from a chair, wall, or box.
3. **Triad Fusion (PIR + Ultrasonic + IMU)**:
   - When `PIR == 1` AND ultrasonic distance is within human detection corridor ($20\text{ cm} \le d \le 250\text{ cm}$):
   - Justified classification: `POSSIBLE_HUMAN_PRESENCE` with target distance $d\text{ cm}$ and relative bearing $\theta^\circ$.
4. **MPU6050 Alone**:
   - Provides relative angular velocity ($g_z$), dynamic tilt (pitch/roll), and dead-reckoned heading offset.
   - Never claim absolute global GPS coordinates.

---

## 5. Reactive Obstacle Evasion & Adaptive Path Replanning

When navigating forward:
1. **Detection**: Ultrasonic distance drops into warning corridor ($25\text{--}40\text{ cm}$).
2. **Brake**: Stop forward drive immediately.
3. **Look Left**: Reverse $5\text{ cm}$, turn $-35^\circ$ to the left, sample distance $d_{\text{left}}$.
4. **Look Right**: Turn $+70^\circ$ (which is $+35^\circ$ relative to initial center), sample distance $d_{\text{right}}$.
5. **Path Selection**:
   - If $d_{\text{left}} > d_{\text{right}}$ and $d_{\text{left}} > 40\text{ cm}$: Pivot left into open corridor.
   - If $d_{\text{right}} \ge d_{\text{left}}$ and $d_{\text{right}} > 40\text{ cm}$: Pivot right into open corridor.
   - If both corridors are blocked ($< 40\text{ cm}$): Reverse $20\text{ cm}$ and execute $180^\circ$ turn.
6. **Resume**: Proceed along clear vector and continue fulfilling the active objective.

---

## 6. Hardware Fail-Safe Safety Supervisor

The safety supervisor operates as an unconditional gatekeeper:
- **Emergency Barrier Cutoff**: Distance $\le 15.0\text{ cm}$ unconditionally cuts all motor PWM power.
- **Tipping Hazard Cutoff**: Pitch $> 35^\circ$ or Roll $> 35^\circ$ immediately cuts motor power.
- **Directional Safety Filter**: When an obstacle is in close proximity ($15\text{--}25\text{ cm}$), forward motion commands are blocked, but reverse and rotational evasion maneuvers are permitted.

---

## 7. Bidirectional Communication Protocols

### A. USB Serial (115200 baud)
- 20Hz JSON Telemetry line-delimited stream:
  ```json
  {"type":"telemetry","device":"BUPI_ESP32","distance_cm":45.2,"pir":0,"ax":0.02,"ay":0.01,"az":0.99,"gx":0.1,"gy":-0.2,"gz":0.0,"pitch":1.2,"roll":-0.8,"heading":184.2,"obstacle":false,"moving":true}
  ```
- Command Receiver: Accepts JSON commands:
  ```json
  {"action":"MOVE_FORWARD","speed":200,"duration_ms":1500}
  {"action":"TURN_LEFT","speed":180,"duration_ms":450}
  {"action":"STOP"}
  ```

### B. WiFi WebSocket (`ws://192.168.0.106:8767`)
- Auto-announces capabilities: `["differential_drive","PIR","HC-SR04","MPU6050"]`.
- Heartbeat every 5000ms.
- Full bidirectional mirror of the USB Serial telemetry stream.
