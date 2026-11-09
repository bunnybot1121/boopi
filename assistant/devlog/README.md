# 📖 BUPI Engineering DevLog & Living Knowledge Base

Welcome to the **BUPI Autonomous Robotics Engineering DevLog**. This directory maintains an immutable, chronological technical record of architecture decisions, firmware developments, hardware discoveries, critical bugs encountered, and exact post-mortem solutions.

---

## 🗂️ Chronological DevLog Index

| Date | Title | Key Systems Covered | Status |
|---|---|---|---|
| **2026-11-09** | [Dual-Ultrasonic + Dual-Servo 2.5D/3D Volumetric Mapping](./2026-11-09_dual_ultrasonic_dual_servo_3d_scanning.md) | Dual HC-SR04 (`GPIO 5/18` & `19/23`), Dual Servos (`13 & 16`), Single-Pass $\Delta d$, 3D Voxels, A* 2.5D | 🟢 Complete |
| **2026-11-07** | [Hardware Servo-Driven Sweeping Turret Upgrade](./2026-11-07_hardware_servo_turret_upgrade.md) | ESP32 Core 2.x/3.x LEDC PWM, Bidirectional Sweep Engine, 2-Way Serial `SERVO_CFG`, 3D Voxel Turret Mapping | 🟢 Complete |
| **2026-11-06** | [Phase 1 Ultrasonic 2.5D/3D Vision Testbed & Hardware Integration](./2026-11-06_phase1_sonar_vision_breakthrough.md) | ESP32 Firmware, Log-Odds DIP Grid, 3D Voxels, Serial Lock Watchdog, Hand-Sweep Calibration | 🟢 Complete |
| **2026-10-25** | [100% Offline AI Subsystem (Ollama, Faster-Whisper, Piper) & Latency Optimization](./2026-10-25_offline_intelligence_subsystem.md) | Edge LLM, INT8 Faster-Whisper, Piper TTS, Electron Mutex Bug Fix, TTFT <770ms | 🟢 Complete |
| **2026-09-26** | [20Hz Closed-Loop Autonomy, Heterogeneous Multi-Rover Fleet, and SIH Audit](./2026-09-26_fleet_autonomy_and_hardware_audit.md) | Dual-Rover Swarm (Bot 1 vs Bot 2), TB6612FNG H-Bridge, 5-Stage Detour, SIH Dossier | 🟢 Complete |
| **2026-08-31** | [CUDA GPU Acceleration, Desktop Launcher, and System Stabilization](./2026-08-31_cuda_acceleration_and_launcher.md) | TensorRT FP16 Acceleration, Start Bupi.bat, OneDrive Path Resolution | 🟢 Complete |
| **2026-06-03** | [Rive Mascot Integration, Procedural Viseme Lip-Sync, and UI Personality](./2026-06-03_rive_mascot_and_viseme_sync.md) | OpenHumans Rive Runtimes, Syllable Lip-Sync, Viseme FFT Mapper, Thought Bubbles | 🟢 Complete |
| **2026-05-20** | [Hybrid LLM Router, Whisper STT, and Desktop Automation Core](./2026-05-20_hybrid_llm_router_and_voice.md) | Intent Classification, Whisper small.en, Dynamic VAD, Terminal Streamer | 🟢 Complete |

---

## 📋 DevLog Entry Template

When writing a new daily entry, use this standard structure:

```markdown
# DevLog: [YYYY-MM-DD] — [Title]

## 1. Executive Summary
- Brief 2-3 sentence overview of what was accomplished today.

## 2. Features & Architecture Implemented
- Component A: ...
- Component B: ...

## 3. Blockers Encountered & Solutions (Troubleshooting Playbook)
### Problem: [Exact Error / Behavior]
- **Symptoms**: ...
- **Root Cause**: ...
- **Resolution / Code Fix**: ...

## 4. Hardware Realities & Pinouts
- Pin mapping, voltage levels, sensor constraints.

## 5. End-of-Day Git Actions
- Recommended git commit commands.
```
