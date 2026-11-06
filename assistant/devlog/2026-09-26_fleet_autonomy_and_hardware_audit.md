# DevLog: 2026-09-26 — 20Hz Closed-Loop Autonomy, Heterogeneous Multi-Rover Fleet, and SIH Audit

## 1. Executive Summary
Designed and validated BUPI's **Mode 2: Autonomous Robotics Swarm** architecture for Smart India Hackathon (SIH 2026 Problem Statement 26201). Deployed the 20Hz closed-loop autonomy engine, integrated the TB6612FNG dual DC motor driver with ESP32, and generated the comprehensive 31-part technical architecture audit.

---

## 2. Features & Architecture Implemented
- **Heterogeneous Dual-Rover Architecture**:
  - **Bot 1 (Scout Rover)**: Agile pathfinder with HC-SR04 sonar array, 6-axis MPU-6050 IMU, and PIR motion sensor.
  - **Bot 2 (Specialist Rover)**: Environmental sensing payload with gas, thermal, and high-traction chassis.
- **20Hz Closed-Loop Autonomy Engine (`motion/kinematics.py`, `firmware/bupi_esp32_firmware.ino`)**:
  - Non-blocking 50ms tick loop coordinating sensory intake, reflex stops, and differential steering.
- **5-Stage Reactive Obstacle Detour Engine**:
  - `Stage 0: Cruise` -> `Stage 1: Slow Approach (<40cm)` -> `Stage 2: Emergency Reflex Stop (<15cm)` -> `Stage 3: Sonar Sector Scan` -> `Stage 4: Turn towards Clear Path`.
- **Dynamic C++ Auto-Flasher**: Pipeline capable of synthesizing and flashing Arduino C++ sketches directly to connected microcontrollers over serial.

---

## 3. Blockers Encountered & Solutions
### Blocker: Motor Stalling & Microcontroller Hangs on Sensor Reads
- **Symptoms**: ESP32 froze during ultrasonic reads, causing DC motors to continue driving forward into walls.
- **Root Cause**: `pulseIn()` was called without a strict timeout (hanging up to 1 second on lost echoes), and TB6612FNG standby pin was floating.
- **Resolution**:
  - Clamped `pulseIn` timeout strictly to `18000 µs` (~3.1m max range), guaranteeing the loop never hangs.
  - Added hardware pull-down on `STBY` and forced motor PWM to zero instantly if loop latency exceeds 80ms.

---

## 4. End-of-Day Git Action
```bash
git add .
git commit -m "feat: complete technical architecture audit, 20Hz closed-loop autonomy, and multi-robot fleet orchestration"
```
