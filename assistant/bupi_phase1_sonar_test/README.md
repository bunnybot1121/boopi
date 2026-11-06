# BUPI Phase 1: Standalone Ultrasonic Vision & 2.5D/3D Plotting Testbed

**Project**: `bupi_phase1_sonar_test`  
**Target**: Isolated validation testbed for ESP32 HC-SR04 spatial imaging before integration into the BUPI disaster-response robot fleet.

---

## 1. Hardware Setup & Pinout Reality

### Hardware Components
- **1x ESP32 Dev Module** (Micro-USB connected to Laptop @ `115200` baud).
- **1x HC-SR04 Ultrasonic Sensor**.
- **0x Servo Motors**: Designed specifically for **hand-held scanning** (rotate & tilt by hand).
- **Optional 1x MPU-6050 6-Axis IMU**: Automatically detected via I2C (`0x68`/`0x69`). If disconnected, seamlessly falls back to the Web UI's virtual sweep pacer.

### Pinout Table

| Peripheral | Sensor Pin | ESP32 GPIO | Electrical Connection Notes |
|---|---|---|---|
| **HC-SR04** | `VCC` | `VIN (5V)` | Requires 5V power for full acoustic output |
| **HC-SR04** | `GND` | `GND` | Common Ground |
| **HC-SR04** | `TRIG` | `GPIO 5` | 3.3V logic is compatible with HC-SR04 trigger |
| **HC-SR04** | `ECHO` | `GPIO 18` | **Crucial**: Use 5V-to-3.3V divider (`1kΩ` series + `2kΩ` to GND) |
| **MPU6050 (Optional)** | `VCC` | `3.3V` | Standard 3.3V power |
| **MPU6050 (Optional)** | `GND` | `GND` | Common Ground |
| **MPU6050 (Optional)** | `SDA` | `GPIO 21` | Hardware I2C Data (`Wire.h`) |
| **MPU6050 (Optional)** | `SCL` | `GPIO 22` | Hardware I2C Clock (`Wire.h`) |

---

## 2. ESP32 Firmware Flashing

1. Sketch location: `esp32_firmware/bupi_phase1_sonar_node/bupi_phase1_sonar_node.ino`
2. Open in Arduino IDE.
3. Select Board: **ESP32 Dev Module**.
4. Baud Rate: **115200**.
5. Upload the sketch.
6. The firmware immediately begins outputting clean newline-delimited JSON lines at ~16.6 Hz (60 ms):
   ```json
   {"ts":12450,"d_cm":78.4,"valid":1,"imu":false,"yaw":null,"pitch":null}
   ```

---

## 3. Laptop "Hive Mind" Quickstart

### Prerequisites
Ensure Python 3.9+ is installed. Install dependencies:
```bash
cd bupi_phase1_sonar_test
pip install -r requirements.txt
```

### Launch Server
Run the FastAPI + WebSocket server on port `8050`:
```bash
python -m uvicorn backend.server:app --port 8050
```
Open your browser at:
```
http://localhost:8050
```

*Note: The server launches with the **Synthetic Room Simulator** running out-of-the-box, allowing you to test all three viewports immediately without plugging in the ESP32!*

---

## 4. The 4 Hand-Sweep Aiming Modes (No Servo Needed)

Since you don't have a servo motor yet, you can physically aim the HC-SR04 in your hand using 4 selectable modes:

1. **Mode 1 — Auto-Paced Radar Guide (Default)**:
   - A smooth sweeping pacer line oscillates across `0° -> 180° -> 0°` on the radar scope.
   - Adjust the sweep period (`3s to 10s`).
   - Rotate the sensor in your hand matching the on-screen pacer needle while it continuously paints the room.
2. **Mode 2 — Manual Step Plotter (`SPACEBAR` / Click)**:
   - Aim the sensor in a fixed direction (`0°, 15°, 30°, ...`).
   - Press **`SPACEBAR`** (or click "Ping & Lock"): it takes a median of 5 pings, locks that wedge into the occupancy grid, and automatically advances 15° to the next angle.
3. **Mode 3 — Interactive Slider / Dial**:
   - Manually drag the angle dial on screen while aiming the sensor in the physical room.
4. **Mode 4 — MPU6050 Live Wrist Tracking**:
   - If an MPU6050 is connected to the sensor, the firmware detects it at boot and streams live `yaw` and `pitch`.
   - Your natural wrist movements aim the radar in real time!
   - Tilting upward (`pitch > 18°`) automatically switches to **Pass 2 (High/Tilted)**.

---

## 5. 2.5D/3D Depth Profiling Explained

- **120x120 Bayesian Log-Odds Grid**:
  $4.8\text{m} \times 4.8\text{m}$ room at $4.0\text{ cm}$ per cell. Bresenham ray-casting and a $15^\circ$ Gaussian acoustic beam model clear free space ($l_{\text{free}} = -0.35$) and increment obstacle hit probability ($l_{\text{hit}} = +0.85$).
- **Horizontal Discontinuity ($\Delta d_{\text{horiz}} > 35\text{ cm}$)**:
  Marks doorways and depth portals (rendered in glowing **Magenta**).
- **Two-Pass Vertical Comparator ($\Delta d_{\text{vert}} = d_{\text{high}} - d_{\text{low}}$)**:
  - Sweep the room flat at ground level (**Pass 1**), then tilt upward (**Pass 2**):
  - $|d_{\text{high}} - d_{\text{low}}| < 15\text{ cm}$ &rarr; **Tall Solid Wall (Red, 100% Height)**.
  - $d_{\text{high}} - d_{\text{low}} > 35\text{ cm}$ &rarr; **Low Rubble / Step Obstacle (Yellow, 25% Height)** with an **Open Navigable Corridor (Cyan)** behind it!
  - $d_{\text{low}} - d_{\text{high}} > 35\text{ cm}$ &rarr; **Hanging Overhang (Orange)**.

---

## 6. Architecture & Files

```
bupi_phase1_sonar_test/
├── esp32_firmware/
│   └── bupi_phase1_sonar_node/
│       └── bupi_phase1_sonar_node.ino # Non-blocking HC-SR04 + MPU6050 I2C firmware
├── backend/
│   ├── config.py                     # Grid resolution, bounds, Log-Odds constants
│   ├── log_odds_grid.py              # Bayesian occupancy grid & Bresenham cone raycaster
│   ├── depth_profiler.py             # Horizontal portals & two-pass vertical comparator
│   ├── cv_pipeline.py                # OpenCV grayscale, semantic RGB, & dilation buffer
│   ├── sonar_imaging_engine.py       # Master spatial coordinator
│   ├── serial_manager.py             # COM port reader & synthetic room simulator
│   └── server.py                     # FastAPI REST API + WebSocket broadcaster
├── frontend/
│   ├── tokens.css                    # Military-spec tactical dark theme tokens
│   ├── styles.css                    # Responsive HUD styling (375px, 768px, 1280px)
│   ├── index.html                    # 3 Viewports layout & control panel
│   ├── modules/
│   │   ├── api.js                    # REST + WebSocket client
│   │   ├── sweep_controller.js       # 4 hand-sweep modes & pacer engine
│   │   ├── polar_scope.js            # Viewport 1: Radar scope canvas
│   │   ├── dip_canvas.js             # Viewport 2: 2D DIP Occupancy canvas
│   │   └── voxel_view.js             # Viewport 3: 3D/2.5D Isometric Voxel World
│   └── app.js                        # Master frontend application
├── requirements.txt
└── README.md
```

