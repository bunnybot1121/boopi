# DevLog: 2026-11-07 — Hardware Servo-Driven Sweeping Turret Upgrade

## 1. Executive Summary
- **Upgrade Objective**: Transform BUPI's Phase 1 Ultrasonic Vision system from a static single-beam sensor into an active **Hardware Servo-Driven Sweeping Turret** (`1x ESP32 + 1x Servo Motor (GPIO 13) + 1x HC-SR04 (TRIG=5, ECHO=18)`).
- **Core Problem Resolved**: Previously, without hardware positioning feedback, spatial imaging was restricted to manual hand-sweeping or virtual pacing, often locking the sonar beam onto a single line. With a physical servo motor stepping across an active sector (default $45^\circ \text{ to } 135^\circ$, centered at $90^\circ$ straight ahead), the ESP32 now streams synchronized `(servo_angle, distance_cm)` telemetry over high-speed USB Serial (115200 baud).
- **Key Outcome**: Viewport 1 (Polar Radar Scope), Viewport 2 (2D DIP Occupancy Matrix), and Viewport 3 (3D Voxel Room Model) now dynamically render the full forward fan in real time with continuous multi-channel depth mapping.

---

## 2. Hardware Architecture & Pinout
| Component | Pin / Interface | Function | Technical Details |
|---|---|---|---|
| **Servo Motor** | `GPIO 13` | Azimuth Turret Actuator | 50 Hz PWM (`500 µs` to `2400 µs`), 180° sweep span |
| **HC-SR04 TRIG** | `GPIO 5` | Ultrasonic Acoustic Burst | 10 µs high pulse |
| **HC-SR04 ECHO** | `GPIO 18` | Time-of-Flight Reception | 25,000 µs timeout (~400 cm ceiling) |
| **MPU6050 (Optional)** | `SDA = 21, SCL = 22` | Inertial Pitch/Roll Failsafe | Auto-detected on I2C (`0x68`/`0x69`) |
| **Power Bus** | `VIN (5V) & GND` | Transducer / Motor Rail | Dedicated 5V required for HC-SR04 piezoelectric oscillation |

---

## 3. Firmware Innovations (`firmware/bupi_sonar_vision_node/`)
1. **LEDC PWM Core 2.x & 3.x Universal Abstraction**:
   - Arduino-ESP32 Core 3.0 deprecated `ledcSetup` / `ledcAttachPin` in favor of `ledcAttach(pin, freq, res)`. Implemented preprocessor macro switching (`ESP_ARDUINO_VERSION_MAJOR >= 3`) to guarantee 100% compilation across all Arduino IDE core versions without third-party library dependencies.
2. **Bidirectional Sector Sweep Engine**:
   - Stepper state machine sweeps smoothly between `min_angle` ($45^\circ$) and `max_angle` ($135^\circ$) in configurable steps (default $3^\circ$).
   - Enforces a $30\text{ ms}$ mechanical settle delay before ultrasonic pinging to eliminate mechanical vibration noise and acoustic flight distortion.
   - Employs a 3-sample median filter for spurious echo rejection.
3. **Two-Way Serial Protocol (`SERVO_CFG`)**:
   - ESP32 listens asynchronously on Serial RX for dynamic reconfiguration commands:
     ```json
     {"cmd": "SERVO_CFG", "min_angle": 45, "max_angle": 135, "step": 3, "settle_ms": 30}
     ```
   - Supports instant manual angle override (e.g., `{"cmd": "SERVO_CFG", "center": true}` to lock at $90^\circ$ for mechanical alignment).

---

## 4. Hive Mind Software Updates (Python & Web HUD)
1. **Backend Integration (`serial_manager.py`, `sonar_imaging_engine.py`, `server.py`)**:
   - `SerialManager` unpacks `"s_ang"`, computes directional hysteresis (`SWEEPING LEFT <-` vs `-> SWEEPING RIGHT`), and fuses IMU orientation if present.
   - `SonarImagingEngine` routes `s_ang` directly into the $120 \times 120$ Log-Odds Bayesian occupancy grid and polar history buffer.
   - `FastAPI` server exposes `POST /api/servo_cfg` and real-time WebSocket command channels (`servo_cfg`, `center_servo`, `resume_sweep`).
2. **Occupancy Grid Sensitivity Optimization (`log_odds_grid.py`)**:
   - Removed arbitrary distance threshold lockout so valid deep open corridors (up to 390 cm) actively clear free floor space (`l_free = -0.35`) while correctly filtering out missed echoes (`valid: 0`).
3. **Frontend HUD Enhancements (`bupi_phase1_sonar_test/frontend/`)**:
   - **Mode 0 Tab**: Hardware Servo Turret set as primary default mode.
   - **Tactical Controls**: Added quick sector presets (`60°–120°`, `45°–135°`, `0°–180°`), min/max angle sliders, step size selector, and alignment buttons ("🎯 Center at 90°", "▶ Resume Sweep").
   - **Status Bar Metrics**: Added live `SERVO ANGLE: XX°` and `SWEEP DIR: <- / ->` telemetry badges.
   - **Polar Scope Wedge**: Highlights active sweep sector with dashed cyan boundary lines and subtle radial shading.

---

## 5. Verification & Unit Tests
- Executed unit test suite `tests/test_bupi_sonar_pipeline.py`:
  - `test_01_synthetic_stream`: PASSED
  - `test_02_log_odds_raycasting`: PASSED
  - `test_03_dip_morphology_and_corridors`: PASSED
  - `test_04_3d_discontinuity_and_voxels`: PASSED
  - `test_05_ai_decision_engine`: PASSED
  - `test_06_state_summary_contract`: PASSED
- **Result**: 6/6 tests passing (100% green).

---

## 6. End-of-Day Git Actions
```bash
git add .
git commit -m "feat(servo-turret): hardware servo-driven sweeping sonar vision with 2-way serial control"
git push origin main
```
