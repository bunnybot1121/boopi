# DevLog: 2026-11-09 — Dual-Ultrasonic + Dual-Servo 2.5D/3D Volumetric Mapping

## 1. Executive Summary
- **Major Milestone**: Implemented the complete, production-ready **Dual-Ultrasonic + Dual-Servo 2.5D/3D Spatial Scanning & Volumetric Mapping Pipeline** across our ESP32 firmware, Python FastAPI backend, and BUPI Test Interface HUD.
- **Hardware Integration**:
  - Sensor 1 (Low / Primary Beam): `TRIG_1 = GPIO 5`, `ECHO_1 = GPIO 18` (5V Echo shifted via $1\text{k}\Omega + 2\text{k}\Omega$ divider).
  - Sensor 2 (High / Tilted / Secondary Beam): `TRIG_2 = GPIO 19`, `ECHO_2 = GPIO 23` (Labeled `D23` on board, or `VP/36`).
  - Servo 1 (Azimuth / Yaw 1): `GPIO 13` (50 Hz PWM).
  - Servo 2 (Elevation / Yaw 2): `GPIO 16` (50 Hz PWM).
  - MPU6050 IMU: `SDA = GPIO 21`, `SCL = GPIO 22` (auto-detected on `0x68`/`0x69`).
- **Core Achievement**: Converted the system from sequential two-pass hand-sweeping into a simultaneous, single-pass real-time differential depth scanner ($\Delta d = d_2 - d_1$), delivering classified 3D voxels (Tall Walls, Low Step/Rubble with open floor penetration behind, Overhang Hazards, Doorway Portals) at ~16 Hz with zero synthetic dummy data.

---

## 2. Firmware Implementation (`firmware/bupi_sonar_3d_scanner/`)
1. **Anti-Brownout Staggered Motion**:
   - Both servos driven at 50 Hz using Core 2.x and Core 3.x universal LEDC hardware PWM abstraction.
   - Servo 1 steps $\rightarrow$ 15 ms delay $\rightarrow$ Servo 2 steps $\rightarrow$ 25 ms mechanical settling delay before pinging.
2. **Anti-Crosstalk Acoustic Firing**:
   - Sequential firing: Sensor 1 pings ($10\,\mu\text{s}$ pulse, $25,000\,\mu\text{s}$ timeout) $\rightarrow$ 12 ms delay for acoustic reverberations to decay $\rightarrow$ Sensor 2 pings.
   - 3-sample rolling median filter on both sensors.
   - Tier-1 Deterministic Safety Stop: sets `"safety_stop": 1` immediately if either sensor sees a valid obstacle $< 18.0\text{ cm}$.
3. **Three Hardware Scan Modes**:
   - `STACKED_3D` (Default): Both servos sweep identical forward sector ($45^\circ \text{ to } 135^\circ$ in $3^\circ$ steps) in sync. S1 scans low plane ($h_1 = 4\text{ cm}$); S2 scans high plane ($h_2 = 14\text{ cm}$ or $+12^\circ$ pitch).
   - `OPPOSED_360`: S1 sweeps Front ($0^\circ\text{–}180^\circ$), S2 faces Rear ($+180^\circ$ offset) for $360^\circ$ coverage.
   - `PITCH_TILT_3D`: S1 sweeps Yaw ($45^\circ\text{–}135^\circ$), S2 steps Pitch ($0^\circ \text{ to } +30^\circ$) at each turnaround for multi-layer 3D mesh scanning.
4. **Strict JSON Protocol (`115200` baud)**:
   - Streams newline-delimited telemetry packets:
     ```json
     {"bot_id":"BUPI-01","ts":15230,"mode":"STACKED_3D","s1_ang":84,"s2_ang":84,"d1_cm":52.4,"d2_cm":178.0,"delta_d":125.6,"valid1":1,"valid2":1,"safety_stop":0,"imu":false,"yaw":null,"pitch":null}
     ```
   - Two-way command parsing: `{"cmd":"SCAN_CFG","mode":"STACKED_3D","min_ang":45,"max_ang":135,"step":3,"sweep_en":1,"center_90":0}`.

---

## 3. Volumetric Mapping Engine (`bupi_phase1_sonar_test/backend/`)
1. **Multi-Layer 120x120 Spatial Tensor ($4.0\text{ cm}$/cell = $4.8\text{m} \times 4.8\text{m}$, origin at $(60, 60)$)**:
   - **Layer 0 (Log-Odds Grids)**: `grid_low` and `grid_high` integrated with Bresenham raycasting and a $15^\circ$ Gaussian cone ($l_{\text{free}} = -0.35, l_{\text{hit}} = +0.85$).
   - **Layer 1 (Single-Pass $\Delta d$ Classifier)**:
     - `OPEN_CORRIDOR` (Cyan, $Z = 0\text{ cm}$): Clear floor up to obstacles.
     - `LOW_STEP_RUBBLE` (Yellow, $Z = 6\text{ cm}$ / 25% height): $d_1$ hits near object and $d_2 - d_1 > 30\text{ cm}$. Cells between $d_1$ and $d_2$ are carved out as open floor behind the rubble!
     - `TALL_SOLID_WALL` (Red, $Z = 25\text{ cm}$ / 100% height): $|d_2 - d_1| \le 25\text{ cm}$.
     - `OVERHANG_HAZARD` (Orange, $Z = 12\text{ to } 25\text{ cm}$ floating): $d_1 - d_2 > 30\text{ cm}$.
     - `DOORWAY_DEPTH_PORTAL` (Magenta): Horizontal depth discontinuity between steps $|d_1(\theta_t) - d_1(\theta_{t-1})| \ge 40\text{ cm}$.
   - **Layer 2 (3D Point Cloud)**: True $X, Y, Z$ Cartesian coordinates in centimeters.
   - **Layer 3 (A* 2.5D Pathfinding & Dilation)**: Dilates walls by 3 cells ($12\text{ cm}$ safety radius); costs: 1.0 for corridor, 4.5 for climbable low step, $\infty$ for tall walls.

---

## 4. Test Interface UI Upgrades (`bupi_phase1_sonar_test/frontend/`)
1. **Top Control Bar**: Added Scan Mode selector, "🎯 Lock Both Servos 90°" button, and "Clear / New 3D Scan" button.
2. **Prominent Dual Readout Bar**: Displays live `S1/D1 (Low)`, `S2/D2 (High)`, `Depth Diff (Δd)`, `3D Class`, and `Safety Stop (<18cm)`.
3. **Viewport 1 (Dual-Beam Radar Scope)**: Renders both Beam 1 (Cyan/Red) and Beam 2 (Amber/Green) cones, needles, and differential bridge line.
4. **Viewport 2 (2D DIP Semantic Matrix)**: Renders classified multi-channel map with A* path overlay and interactive metric hover.
5. **Viewport 3 (True 3D Voxel World — Three.js)**: Full-height Tall Walls, quarter-height Low Steps with visible open corridor floor behind, floating Overhang blocks, glowing Portal rings, and Dual 3D Beams emitted from the robot chassis.
6. **AI Sector Panel**: 5-sector table with obstacle classifications and traversability %, plus live 20x20 ASCII semantic map.

---

## 5. Verification & Unit Tests
- `tests/test_bupi_sonar_pipeline.py`: 8/8 tests passed (100% green, 0.67s execution).
  - Validated coordinate transformations, Bayesian cone integration, single-pass $\Delta d$ depth classification, 3D point cloud generation, 2.5D A* pathfinding, and FastAPI dual-ping REST/WebSocket endpoints.

---

## 6. Motor Motion Smoothing Upgrade (S-Curve Hermite Interpolation)
- **Problem**: Previous discrete $3^\circ$ step jumps caused mechanical chattering, gear vibration, and hard turnaround bounces at sector limits ($45^\circ/135^\circ$).
- **Solution**:
  1. **Floating-Point Sub-Degree Resolution**: Upgraded LEDC 14-bit PWM duty calculation to accept `float angle_deg`, achieving $0.11^\circ$ physical step resolution.
  2. **Quintic Smoothstep S-Curve Easing**: Implemented $S(t) = 6t^5 - 15t^4 + 10t^3$ over 35ms micro-stepped intervals, guaranteeing zero velocity and zero acceleration jerk at motion onset and termination.
  3. **Soft Boundary Deceleration**: Harmonic cosine deceleration factor applied within $12^\circ$ of sweep limits (`min_ang` / `max_ang`), easing into a smooth turnaround rather than a mechanical impact.
  4. **Anti-Brownout PWM Staggering**: 2ms stagger between Servo 1 and Servo 2 updates to prevent inductive inrush current spikes.


