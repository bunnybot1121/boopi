# DevLog: 2026-11-06 — Phase 1 Standalone Ultrasonic Vision & 2.5D/3D Plotting Testbed

## 1. Executive Summary
Today we built, verified, and stabilized the complete **Phase 1 Ultrasonic 2.5D/3D Spatial Vision System** (`bupi_phase1_sonar_test`). The system turns inexpensive HC-SR04 ultrasonic sensors into a camera-less spatial depth mapping matrix on the Laptop ("Hive Mind"). We developed the ESP32 firmware, replaced all simulator mockups with 100% physical hardware streaming, fixed the 3D voxel extrusion pipeline, resolved multiple Windows-specific serial port collisions, and adapted the engine for physical hand-sweeping without a servo.

---

## 2. Features & Architecture Implemented

### Component A: ESP32 Firmware (`firmware/esp32_sonar_vision/esp32_sonar_vision.ino`)
- Non-blocking HC-SR04 ping on `TRIG = GPIO 5` and `ECHO = GPIO 18` with strict `25000 µs` (`400 cm`) timeout.
- 3-sample rolling median filter to eliminate acoustic outlier spikes before serial transmission.
- Hardware auto-detection for MPU6050 on I2C (`0x68`/`0x69`) with 100-sample gyro resting calibration.
- Continuous 16 Hz newline-delimited JSON stream at `115200` baud:
  ```json
  {"ts": 1234, "d_cm": 187.9, "valid": 1, "safety_stop": 0, "imu": false, "yaw": null, "pitch": null}
  ```

### Component B: Laptop Hive Mind Imaging Engine (`bupi_phase1_sonar_test/backend/`)
- **Bayesian Log-Odds Occupancy Grid (`log_odds_grid.py`)**:
  - $120 \times 120$ spatial grid at $4.0\text{ cm}$ resolution ($4.8\text{m} \times 4.8\text{m}$ area).
  - 15-degree Gaussian acoustic cone beam model clearing free space ($l_{\text{free}} = -0.35$) and accumulating obstacle probability ($l_{\text{hit}} = +0.85$).
- **Differential Depth & Elevation Profiler (`depth_profiler.py`)**:
  - *Horizontal Discontinuity Detector*: Flags $\Delta d_{\text{horiz}} > 35\text{ cm}$ as a 3D Depth Portal / Doorway opening.
  - *Two-Pass Vertical Comparator*: Compares Pass 1 (flat layer) vs Pass 2 (tilted layer) to distinguish Tall Solid Walls ($100\%$ height) from Low Rubble Steps ($25\%$ height).
- **AI Map Decision Reader (`ai_map_decision_reader.py`)**:
  - 5-Sector Clearance analysis (`Left`, `Front-Left`, `Center`, `Front-Right`, `Right`).
  - Real-time 2D A* navigation path calculation and steering recommendation.
  - Live $20 \times 20$ ASCII Semantic Matrix generation.

### Component C: Web Testbed & 3D Voxel Viewport (`frontend/`)
- Viewport 1: Live Polar Radar Scope with phosphor sweep persistence and range rings.
- Viewport 2: 2D DIP Occupancy matrix showing dilated collision safety buffers.
- Viewport 3: Three.js 3D Voxel Extrusion rendering tall red walls, yellow steps, flat cyan floor, green robot origin, and planned path.
- Completely purged all synthetic simulator buttons and mock loops.

---

## 3. Blockers Encountered & Solutions (Troubleshooting Playbook)

### Blocker 1: `COM3` Access Denied on Windows
- **Symptoms**: Python failed with `SerialException: could not open port 'COM3': PermissionError(13, 'Access is denied.')`.
- **Root Cause**: On Windows, serial COM ports are strictly single-process exclusive. The Arduino IDE Serial Monitor was open, locking the COM3 handle.
- **Resolution**:
  - Closed the Arduino Serial Monitor tab.
  - Built an active background watchdog in `backend/serial_manager.py` that continuously probes for `COM3`. The watchdog auto-detects when the port is busy, displays an amber badge in the UI, and automatically connects the instant the port is released.

### Blocker 2: Win32 Handle Collision & Python 3.14 Crash (`0xc0000005`)
- **Symptoms**: Repeatedly clicking "Connect" in the web UI crashed uvicorn with Win32 Access Violation `0xc0000005`.
- **Root Cause**: Rapid asynchronous HTTP requests triggered multiple concurrent calls to `serial.Serial()` while the reader background thread was inside a blocking Win32 `ReadFile`.
- **Resolution**: Added a `threading.Lock()` mutex around all port open/close operations and implemented a graceful thread stop event with `.join(timeout=0.3)` before closing serial handles.

### Blocker 3: Phantom Sweeps & Fake Readings Without a Servo
- **Symptoms**: The software radar beam kept oscillating back and forth automatically, mapping stationary hand readings across random angles and clearing the whole room as a flat void.
- **Root Cause**: Mode 1 (Virtual Auto-Pacer) was enabled by default. In Mode 1, a software timer sweeps the angle $0^\circ \to 180^\circ$ at 6 seconds per sweep, which desynchronizes from human hand movement.
- **Resolution**:
  - Changed default aiming mode to **Mode 3: Manual Dial (Hand Aim)**.
  - Added **Interactive Click & Drag on the Polar Radar Scope**: Users can now click or drag anywhere on Viewport 1 to point the sensor angle in real time.
  - Added condition in `log_odds_grid.py` to prevent missed echoes (`valid: 0`) from corrupting the occupancy matrix.

### Blocker 4: Sensor Output Stuck at `d_cm: 400.0, valid: 0`
- **Symptoms**: The sensor output was permanently `400.0 cm` even when waving hands in front of the transducers.
- **Root Cause**: Standard HC-SR04 ultrasonic modules require **5V power (`VIN`)** to oscillate their piezoelectric transducers. When mistakenly connected to the ESP32's **3.3V pin**, the transmitter cannot emit ultrasound, causing `pulseIn` to continuously timeout at 25ms.
- **Resolution**: Moved HC-SR04 `VCC` to the 5V / VIN pin and verified `TRIG` on GPIO 5 and `ECHO` on GPIO 18.

---

## 4. Hardware Pinout & Wiring Reference

| Sensor / Module | Pin Name | ESP32 GPIO | Electrical Notes |
|---|---|---|---|
| **HC-SR04 Ultrasonic** | `VCC` | `VIN` / `5V` | Must be **5V**; 3.3V will cause echo timeouts |
| | `GND` | `GND` | Common ground with ESP32 |
| | `TRIG` | `GPIO 5` | 10 µs active-HIGH pulse |
| | `ECHO` | `GPIO 18` | 5V pulse (optional 1k/2k voltage divider to 3.3V) |
| **MPU-6050 (Optional)**| `VCC` | `3.3V` | 3.3V power |
| | `GND` | `GND` | Common ground |
| | `SDA` | `GPIO 21` | I2C Data (Auto-detected at 0x68 / 0x69) |
| | `SCL` | `GPIO 22` | I2C Clock |

---

## 5. End-of-Day Git Actions

Execute the following commands to commit today's milestones:

```bash
git add .
git commit -m "feat(sonar-vision): Phase 1 Ultrasonic 2.5D/3D testbed, thread-safe COM manager, and DevLog"
git status
```

