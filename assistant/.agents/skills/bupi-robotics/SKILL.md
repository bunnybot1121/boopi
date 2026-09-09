---
name: bupi-robotics
description: Expert robotics intelligence, ESP32 hardware interfaces, sensor fusion, obstacle avoidance, and dynamic natural language mission execution for BUPI.
---

# BUPI Autonomous Robotics Skill

Use this skill when developing, debugging, running, or interacting with the **BUPI Mobile Robot Platform**.

## 1. Hardware Architecture & Pinout Truth Table

BUPI is driven by an **ESP32 Dev Module** running non-blocking 20Hz firmware connected to:

### A. TB6612FNG Dual H-Bridge & Dual N20 Gear Motors
| Pin Name | ESP32 GPIO | Direction | Function |
|---|---|---|---|
| **PWMA** | `25` | Output | Left Motor PWM Speed (0–255, 1kHz LEDC) |
| **AIN1** | `26` | Output | Left Motor Direction 1 |
| **AIN2** | `27` | Output | Left Motor Direction 2 |
| **PWMB** | `14` | Output | Right Motor PWM Speed (0–255, 1kHz LEDC) |
| **BIN1** | `33` | Output | Right Motor Direction 1 (GPIO 33, NOT 32) |
| **BIN2** | `32` | Output | Right Motor Direction 2 |
| **STBY** | `4` | Output | Driver Standby (Must be driven `HIGH`) |
| **VM** | Motor Power | External | 3.7V–6V Battery pack for N20 motors |
| **VCC** | ESP32 3.3V / 5V | Input | Logic Supply |

#### Truth Table:
- **Forward**: `AIN1=HIGH, AIN2=LOW`, `BIN1=HIGH, BIN2=LOW`
- **Reverse**: `AIN1=LOW, AIN2=HIGH`, `BIN1=LOW, BIN2=HIGH`
- **Turn Left**: `AIN1=LOW, AIN2=HIGH` (reverse left), `BIN1=HIGH, BIN2=LOW` (forward right)
- **Turn Right**: `AIN1=HIGH, AIN2=LOW` (forward left), `BIN1=LOW, BIN2=HIGH` (reverse right)
- **Stop**: `AIN1=LOW, AIN2=LOW`, `BIN1=LOW, BIN2=LOW`, PWMs=0

---

### B. Sensors
1. **HC-SR04 Ultrasonic Distance Sensor**:
   - `TRIG`: GPIO `5` (Output, 10µs pulse)
   - `ECHO`: GPIO `18` (Input, 5V-to-3.3V resistor divider recommended: 1kΩ / 2kΩ)
   - Non-blocking pulse timeout: 25ms (~4.2 meters max range)
2. **PIR Infrared Motion Sensor**:
   - `OUT`: GPIO `19` (Digital Input, active `HIGH`)
   - Detection cone: ~100° FOV, range up to 2.5m
3. **MPU6050 6-Axis IMU**:
   - `SDA`: GPIO `21`, `SCL`: GPIO `22` (I2C address `0x68`, 400kHz Fast Mode)
   - Acceleration ($a_x, a_y, a_z$ in Gs)
   - Gyroscope ($g_x, g_y, g_z$ in °/s)
   - Pitch & Roll: calculated from accelerometer
   - Heading / Yaw: integrated from $g_z$ over $\Delta t$

---

## 2. Epistemic Sensor Fusion Rules

Never hallucinate or overclaim certainty beyond physical sensor characteristics:
1. **PIR HIGH alone**:
   - States: `POSSIBLE_WARM_MOVING_TARGET` or `THERMAL_FLUX_DETECTED`.
   - Never output: "Human confirmed" or "Person identified".
2. **Ultrasonic HC-SR04 alone**:
   - Measures geometric distance to acoustic surface. Cannot distinguish humans from furniture, boxes, or walls.
3. **Sensor Fusion (PIR + Ultrasonic)**:
   - When `PIR == 1` AND ultrasonic distance is in human corridor ($20\text{ cm} \le d \le 250\text{ cm}$):
     Classify as: `POSSIBLE_HUMAN_PRESENCE` with estimated distance $d$ and relative bearing $\theta$.
4. **MPU6050 alone**:
   - Tracks relative ego-motion and heading offset. Prohibit any GPS/world coordinates claims.

---

## 3. Hardware Fail-Safe Safety Supervisor

The safety layer is an unconditional hardware gatekeeper:
- **Critical Barrier Cutoff**: If distance $\le 15.0\text{ cm}$, immediately cut motor power.
- **Tilt Hazard Cutoff**: If pitch $> 35^\circ$ or roll $> 35^\circ$, immediately cut motor power.
- **Reverse/Evasion Permission**: When obstacle distance is between $15\text{ cm}$ and $25\text{ cm}$, forward drive is blocked, but reverse and rotational evasion maneuvers are permitted.

---

## 4. Reactive Obstacle Avoidance & Adaptive Path Replanning

When an obstacle enters BUPI's path:
1. **Detect**: Ultrasonic reading drops into warning corridor ($25\text{--}40\text{ cm}$).
2. **Stop**: Halt forward motor movement.
3. **Look Left**: Turn $-30^\circ$, sample ultrasonic distance $d_{\text{left}}$.
4. **Look Right**: Turn $+60^\circ$ ($+30^\circ$ relative to center), sample ultrasonic distance $d_{\text{right}}$.
5. **Decide**:
   - If $d_{\text{left}} > d_{\text{right}}$ and $d_{\text{left}} > 40\text{ cm}$, pivot left into clear corridor.
   - If $d_{\text{right}} \ge d_{\text{left}}$ and $d_{\text{right}} > 40\text{ cm}$, pivot right into clear corridor.
   - If both are blocked ($< 40\text{ cm}$), reverse $50\text{ cm}$ and perform a $180^\circ$ turn.
6. **Resume**: Continue fulfilling the active objective.

---

## 5. Dynamic Mission Execution (Zero If/Else Rigidity)

BUPI decomposes any user instruction into parameterized policies:
- **`CONDITIONAL_MOVE`**: Walk forward/reverse until a sensor condition is met (e.g. *"walk until an obstacle comes in front of you"* $\rightarrow$ stops at ultrasonic $\le 25\text{ cm}$).
- **`SCAN_SWEEP`**: 360° rotational scan correlating PIR and ultrasonic (e.g. *"are there any humans in the room?"* $\rightarrow$ localizes distance and bearing).
- **`MONITOR_HOLD`**: Sentry mode monitoring PIR for motion triggers.
- **`ROTATE_TO`**: Angular turn using IMU heading feedback.
- **`EXPLORE_SAFE`**: Continuous navigation with dynamic obstacle evasion.

### CLI Testing & Direct Query
```bash
# 1. Walk until obstacle
python scripts/query_bupi.py "walk until an obstacle comes in front of you"

# 2. Check for human presence
python scripts/query_bupi.py "BUPI, are there any humans in the room?"

# 3. Interactive prompt mode
python scripts/query_bupi.py
```
