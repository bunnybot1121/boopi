# BUPI: Autonomous Multi-Robot Swarm & Intelligent Desktop Companion

[![SIH Problem Statement 26201](https://img.shields.io/badge/SIH%202026-PS%2026201-blue?style=for-the-badge)](https://www.sih.gov.in/)
[![Architecture](https://img.shields.io/badge/Architecture-Dual--Personality%20Local--First-emerald?style=for-the-badge)](#system-architecture)
[![Decision Engine](https://img.shields.io/badge/Decision%20Engine-3--Tier%20(<5ms%20to%20500ms)-violet?style=for-the-badge)](#3-tier-edge-decision-pipeline)
[![Offline Capable](https://img.shields.io/badge/Robotics%20Mode-100%25%20Offline-green?style=for-the-badge)](#offline-resilience)
[![Electron](https://img.shields.io/badge/UI-Electron%2041.2%20(Chromium)-orange?style=for-the-badge)](https://www.electronjs.org/)

> **Official Repository for Problem Statement 26201**  
> BUPI (Brain-Unified Personal Intelligence & Robotic Controller) is a dual-personality AI robotics platform combining an **always-on desktop productivity companion** with an **offline-first autonomous multi-rover controller** for search-and-rescue, confined-space inspection, and hazardous environment triage.

<div align="center">
  <img src="assets/bupi_dual_rovers.jpg" alt="BUPI Heterogeneous Multi-Rover Swarm: Bot 1 Scout and Bot 2 Specialist" width="100%" style="border-radius: 12px; margin: 16px 0; box-shadow: 0 4px 20px rgba(0,0,0,0.3);" />
  <p><em>Figure 1: Physical hardware deployment of the BUPI heterogeneous multi-rover swarm (Bot 1 Scout &amp; Bot 2 Environmental Specialist).</em></p>
</div>

---

## Table of Contents
- [Executive Overview](#executive-overview)
- [Dual-Personality Operating Modes](#dual-personality-operating-modes)
- [Mode 2: Autonomous Robotics Deep-Dive](#mode-2-autonomous-robotics-deep-dive)
  - [3-Tier Edge Decision Pipeline](#3-tier-edge-decision-pipeline)
  - [Heterogeneous Multi-Rover Swarm (Bot 1 vs Bot 2)](#heterogeneous-multi-rover-swarm-bot-1-vs-bot-2)
  - [20Hz Closed-Loop Autonomy & Mission Engine](#20hz-closed-loop-autonomy--mission-engine)
  - [Reactive 5-Stage Obstacle Detour Engine](#reactive-5-stage-obstacle-detour-engine)
  - [Epistemic Kinematics Odometry](#epistemic-kinematics-odometry)
  - [Multi-Layer Safety Architecture](#multi-layer-safety-architecture)
  - [Dynamic C++ Hardware Ingestion & Auto-Flasher](#dynamic-c-hardware-ingestion--auto-flasher)
  - [Bit-World Engine (BWE) Digital Twin](#bit-world-engine-bwe-digital-twin)
- [Communication & Network Fabric](#communication--network-fabric)
- [Desktop Cockpit & User Interface](#desktop-cockpit--user-interface)
- [Repository Structure](#repository-structure)
- [Quick Start Guide](#quick-start-guide)
- [Technical Documentation Index](#technical-documentation-index)

---

## Executive Overview

Traditional robotic systems face a persistent engineering trilemma when deployed in subterranean, disaster, or edge environments:
1. **Cloud Latency**: Commercial LLMs take 2–6 seconds per call, making reactive collision avoidance impossible.
2. **Connectivity Dependency**: Pure cloud robots freeze when network cables sever or Wi-Fi drops.
3. **Rigid Hardware Silos**: Hardcoded microcontroller pinouts prevent dynamic adaptation to new sensors in the field.

BUPI eliminates these bottlenecks through a **local-first, 3-tier intelligence pipeline**, an isolated **2.4GHz hotspot network fabric**, a **heterogeneous multi-rover swarm**, and an **on-the-fly C++ firmware ingestion engine**.

---

## Dual-Personality Operating Modes

BUPI seamlessly toggles between two distinct operating paradigms:

```
                                 +-----------------------------+
                                 |   BUPI CENTRAL CORE (PC)    |
                                 +-----------------------------+
                                                |
                       +------------------------+------------------------+
                       |                                                 |
                       v                                                 v
        +-----------------------------+                   +-----------------------------+
        |  MODE 1: DESKTOP COMPANION  |                   |  MODE 2: ROBOTICS CONTROLLER|
        +-----------------------------+                   +-----------------------------+
        | • Transparent 3D Mascot     |                   | • 100% Offline 3-Tier AI    |
        | • Faster-Whisper Voice STT  |                   | • 20Hz Closed-Loop Autonomy |
        | • Edge-TTS Neural Voice     |                   | • Dual ESP32 Rover Swarm    |
        | • Gemini Conversational AI  |                   | • Dynamic C++ Auto-Flasher  |
        | • Window Activity Tracking  |                   | • Digital Twin Simulation   |
        +-----------------------------+                   +-----------------------------+
```

| Operational Dimension | Mode 1 (Desktop Companion) | Mode 2 (Autonomous Robotics Controller) |
| :--- | :--- | :--- |
| **Primary Focus** | Daily productivity, note-taking, PC assistance | Subterranean search-and-rescue, gas profiling, multi-bot swarm |
| **UI Experience** | Frameless 250x250 transparent mascot overlay | 1200x800 11-Tab Central Control Hub & 2D Tactical Arena |
| **Decision Stack** | Google Gemini Live API / OpenRouter streaming | Tier 1 Regex (<5ms) $\rightarrow$ Tier 2 Ollama (~500ms) $\rightarrow$ Tier 3 CrewAI |
| **Network Dependency**| Requires Internet for neural voice & cloud LLMs | **100% Offline Capable** (zero internet required) |

---

## Mode 2: Autonomous Robotics Deep-Dive

### 3-Tier Edge Decision Pipeline

BUPI eliminates cloud latency by evaluating user utterances and sensor triggers through a strictly tiered escalation pipeline:

```
Incoming Utterance / Sensor Event
        |
        v
+---------------------------------------------------------------------------------+
| TIER 1: RouterAgent (Deterministic Python Regex)                  Latency: <5ms |
| - Location: agents/router_agent.py                                              |
| - Intercepts: Emergency Stops ("stop", "halt", "freeze"), direct moves, queries.|
| - Guarantees: Zero LLM hallucination, microsecond hardware execution.           |
+---------------------------------------------------------------------------------+
        | (Unmatched / Semantic Intent Required)
        v
+---------------------------------------------------------------------------------+
| TIER 2: LocalAgentOrchestrator (Local Ollama LLM)                Latency: ~500ms|
| - Location: agents/local_orchestrator.py                                        |
| - Model: llama3.2:3b (with automatic fallback to llama3.1:8b)                   |
| - Capabilities: Single-turn function calling with 12 strict OpenAI tool schemas.|
| - Guarantees: 100% offline edge execution for room scans, gas checks, missions. |
+---------------------------------------------------------------------------------+
        | (Ollama Offline / Complex Multi-Step Mission Required)
        v
+---------------------------------------------------------------------------------+
| TIER 3: RoboticCrew (Hierarchical Multi-Agent CrewAI)             Latency: 5-15s|
| - Location: agents/robotic_crew.py                                              |
| - Framework: CrewAI (Scout Analyst + Specialist + Mission Coordinator)         |
| - Sequential Model Fallback Chain:                                              |
|   1. Local Ollama llama3.2:3b                                                   |
|   2. Local Ollama llama3.1:8b                                                   |
|   3. Google Gemini 2.5 Flash                                                    |
|   4. Groq llama-3.3-70b-versatile                                               |
|   5. NVIDIA DeepSeek / OpenRouter                                               |
+---------------------------------------------------------------------------------+
```

---

### Heterogeneous Multi-Rover Swarm (Bot 1 vs Bot 2)

Rather than overloading a single chassis with incompatible sensors, BUPI divides physical labor across two specialized 4-wheel differential-drive rovers:

<div align="center">
  <img src="assets/bupi_dual_rovers.jpg" alt="BUPI Bot 1 Scout and Bot 2 Specialist Hardware Infographic" width="100%" style="border-radius: 10px; margin: 14px 0;" />
</div>

```
+-----------------------------------------+         +-----------------------------------------+
|      BOT 1: RECONNAISSANCE SCOUT        |         |   BOT 2: ENVIRONMENTAL SPECIALIST       |
+-----------------------------------------+         +-----------------------------------------+
| • Client ID: bupi_01                    |         | • Client ID: bupi_02                    |
| • Firmware: firmware/bupi_bot1_scout.ino|         | • Firmware: bupi_bot2_specialist.ino    |
| • Controller: ESP32 Dev Module (240MHz) |         | • Controller: ESP32 Dev Module (240MHz) |
| • Drive: TB6612FNG Dual H-Bridge        |         | • Drive: TB6612FNG Dual H-Bridge        |
| • Motors: 2x N20 Micro Metal Gearmotors |         | • Motors: 2x N20 Micro Metal Gearmotors |
|                                         |         |                                         |
| SENSOR PAYLOAD:                         |         | SENSOR PAYLOAD:                         |
| 1. HC-SR04 Ultrasonic (GPIO 5/18)       |         | 1. HC-SR04 Ultrasonic (GPIO 5/18)       |
| 2. MPU6050 6-Axis IMU (I2C 0x68)        |         | 2. MPU6050 6-Axis IMU (I2C 0x68)        |
| 3. PIR Pyroelectric Motion (GPIO 34/19) |         | 3. MQ-2 Toxic Gas Sensor (GPIO 34 ADC)  |
|                                         |         | 4. DHT22 Climate Sensor (GPIO 4)        |
| MISSION ROLE:                           |         | MISSION ROLE:                           |
| • Rapid corridor navigation             |         | • Atmospheric hazard triage             |
| • Thermal human / survivor detection    |         | • Explosive gas plume tracking          |
| • Sonar boundary mapping                |         | • Temperature & humidity profiling      |
+-----------------------------------------+         +-----------------------------------------+
                     \                                   /
                      \                                 /
                +---------------------------------------------+
                |   SWARM COORDINATOR (swarm_coordinator.py)  |
                |   - Tandem Telemetry Fusion                 |
                |   - Fleet-Wide Evacuation Interlock (>350ppm|
                +---------------------------------------------+
```

---

### 20Hz Closed-Loop Autonomy & Mission Engine

BUPI's autonomous behavior runs in a dedicated 20Hz thread inside `agents/autonomous_goal_agent.py`:

```
                       +------------------------------+
                       | Natural Language Instruction |
                       |  "Find human and check gas"  |
                       +------------------------------+
                                      |
                                      v
                       +------------------------------+
                       |    InstructionDecomposer     |
                       |      DynamicMissionPlan      |
                       +------------------------------+
                                      |
                                      v
+========================================================================================+
|                       AUTONOMOUS GOAL AGENT (20Hz / 50ms Loop)                         |
|                                                                                        |
|  [1. OBSERVE (5ms)]                                                                    |
|   • Fetch latest telemetry from bupi_node_server: HC-SR04, MQ-2, MPU6050, PIR, RSSI    |
|   • Feed readings into kinematics_odometry.process_telemetry()                         |
|                                                                                        |
|  [2. REASON (10ms)]                                                                    |
|   • Evaluate active policy against 11 supported behaviors                              |
|   • Check dynamic stop condition: distance met, survivor found, gas leak, timeout      |
|   • Verify safety boundaries: gas < 300ppm, tilt < 45°                                 |
|                                                                                        |
|  [3. ACT (5ms)]                                                                        |
|   • Calculate motor speed/direction vectors                                            |
|   • Publish command to MQTT: bupi/actuators/motors/cmd/json                            |
|   • Broadcast live coordinates and sensor pings to Electron 2D Arena Canvas            |
+========================================================================================+
```

#### 11 Implemented Mission Policies:
1. `EXPLORE_AND_MAP`: Autonomous corridor exploration with sonar bounds.
2. `PATROL_PERIMETER`: Boundary surveillance traversal.
3. `SURVIVOR_SEARCH`: Heat/motion detection using PIR and forward crawling.
4. `GAS_LEAK_INVESTIGATION`: Concentration gradient tracking toward gas plume source.
5. `TARGET_APPROACH`: Coordinate vector traversal to target.
6. `RETURN_TO_ORIGIN`: Inverse vector traversal back to `(0, 0)`.
7. `OBSTACLE_AVOIDANCE_STAGE`: Intercept stage for obstacle detour.
8. `COLLABORATIVE_SWARM_SWEEP`: Tandem scout + specialist sweep.
9. `SYSTEM_HEALTH_CHECK`: Actuator and sensor verification spin.
10. `STATIONARY_MONITOR`: Sentry mode with threshold alerts.
11. `CUSTOM_DECOMPOSED_POLICY`: Dynamically assembled from user instructions.

---

### Reactive 5-Stage Obstacle Detour Engine

When an obstacle is detected at $\le 15.0\text{ cm}$ during an active mission, `core/obstacle_bypass_engine.py` executes a pure geometric detour without waiting for an LLM:

```
        Obstacle Encountered (<= 15cm)
                     |
       +-------------+-------------+
       |   Stage 1: REVERSE        | (Backs off 15cm from obstacle)
       +-------------+-------------+
                     |
       +-------------+-------------+
       |   Stage 2: PIVOT 60°      | (Rotates right 60° to clear profile)
       +-------------+-------------+
                     |
       +-------------+-------------+
       |   Stage 3: ADVANCE 30cm   | (Moves forward 30cm along lateral flank)
       +-------------+-------------+
                     |
       +-------------+-------------+
       |   Stage 4: COUNTER-PIVOT  | (Rotates left -60° to re-align heading)
       +-------------+-------------+
                     |
       +-------------+-------------+
       |   Stage 5: RESUME MISSION | (Continues along original path)
       +---------------------------+
```

---

### Epistemic Kinematics Odometry

BUPI uses a specialized **Epistemic Kinematics Engine** (`core/kinematics_odometry.py`) optimized for encoder-less N20 DC gearmotors:
* **IMU Dynamic Gait Step Detection**: Calculates total acceleration magnitude:
  $$a_{\text{total}} = \sqrt{a_x^2 + a_y^2 + a_z^2}$$
  Registers a physical step when $a_{\text{total}} \ge 1.20\text{g}$ with a 180ms debounce. Stride length = $0.075\text{ m}$ (7.5 cm) per step. Eliminates false dead-reckoning from wheel slip.
* **Gyro Yaw Dead-Reckoning**: Integrates MPU6050 Z-gyro angular velocity ($\theta = \theta + g_z \times dt$) for continuous heading tracking.
* **Wi-Fi RSSI Log-Distance Path Loss**: Estimates distance from host gateway:
  $$d = 10^{\frac{-42.0 - \text{RSSI}}{25.0}}$$
  Smoothed via EWMA ($\alpha = 0.25$) to bound cumulative dead-reckoning drift.

---

### Multi-Layer Safety Architecture

Safety is enforced in depth across firmware, software, and network layers:

| Layer | Module & Location | Threshold / Trigger | Action Taken | LLM Override? |
| :--- | :--- | :--- | :--- | :---: |
| **Layer 1: Deterministic E-Stop** | `agents/router_agent.py:80` | Regex: `stop`, `halt`, `freeze` | Instant motor cut (`left=0, right=0`) | **NO** (Bypasses LLMs) |
| **Layer 2: Telemetry TTL Watchdog** | `core/safety_validator.py:6` | Telemetry age $> 15.0\text{ s}$ | Rejects new movement commands | **NO** |
| **Layer 3: Gas Hazard Barrier** | `core/safety_validator.py:125` | MQ-2 Gas $> 300\text{ ppm}$ | Blocks forward movement into gas | **NO** |
| **Layer 4: Swarm Evacuation Guard** | `core/swarm_coordinator.py:131` | MQ-2 Gas $> 350\text{ ppm}$ | Broadcasts emergency stop to BOTH rovers | **NO** |
| **Layer 5: Node Heartbeat Guard** | `bupi_node_server.py:184` | Node silence $> 15.0\text{ s}$ | Marks node state as `OFFLINE` | **NO** |
| **Layer 6: Firmware Auto-Stop Reflex** | `bupi_bot1_scout.ino:676` | Command `duration_ms` elapsed | Microcontroller cuts PWM locally | **NO** (Firmware timer) |
| **Chassis Tilt Protection** | `bupi_bot1_scout.ino:88` & `sensor_translator.py` | Software: $\ge 45^\circ$, Firmware: $85^\circ$ | Warning at 45°; hardware rollover cutoff at 85° | **NO** |

---

### Dynamic C++ Hardware Ingestion & Auto-Flasher

BUPI can learn new physical hardware peripherals dynamically without modifying Python core logic:

```
User Pastes Raw Arduino C++ Snippet into Central Hub
                     |
                     v
+---------------------------------------------------------------------------------+
| 1. SQLite FTS5 Knowledge Search (services/knowledge_super_agent.py)             |
|    - Sub-millisecond lookup in fts5_hardware_index.db for pinouts & libraries.  |
+---------------------------------------------------------------------------------+
                     |
                     v
+---------------------------------------------------------------------------------+
| 2. AI Brain Code Synthesis (brain/ai_brain.py:393)                              |
|    - Injects Wi-Fi, MQTT handlers, and JSON telemetry publishers.               |
|    - Appends usage command to hardware_memory.txt.                              |
+---------------------------------------------------------------------------------+
                     |
                     v
+---------------------------------------------------------------------------------+
| 3. Auto-Flasher Execution (actions/flasher.py:21)                               |
|    - Compiles sketch using local arduino-cli binary.                            |
|    - Flashes compiled binary to detected ESP32 COM port.                        |
+---------------------------------------------------------------------------------+
                     |
                     v
+---------------------------------------------------------------------------------+
| 4. Universal MQTT Dispatch (actions/hardware_tools.py:219)                      |
|    - LLMs read hardware_memory.txt and invoke universal_mqtt_tool(topic, cmd).  |
|    - ZERO PYTHON CORE CHANGES REQUIRED.                                         |
+---------------------------------------------------------------------------------+
```

---

### Bit-World Engine (BWE) Digital Twin

Before touching physical hardware, BUPI provides a complete simulated lab environment:
* **Physics & Kinematics**: JavaScript 2D rigid-body engine (`bwe/core/engine.js`).
* **Virtual Peripherals**: Digital GPIO states, PWM duty cycles, 12-bit ADC voltage, virtual I2C/SPI buses.
* **Peripheral Plugins**: HC-SR04 ultrasonic raycasting (`hcsr04.js`), MQ-2 gas plume diffusion modeling (`mq2.js`), servo actuators (`servo.js`), SSD1306 OLED displays (`oled.js`).
* **Hardware-in-the-Loop (HIL)**: `bwe/interface/hil_bridge.js` allows physical ESP32 boards flashing `esp32_bwe_mqtt_client.ino` to connect to virtual environment peripherals over USB Serial.
* **Full Parity**: Telemetry packets use identical JSON schemas; `AutonomousGoalAgent` runs against virtual rovers with zero code changes.

---

## Communication & Network Fabric

```
+------------------------------------------------------------------------------------+
| HOST CONTROLLER NETWORK ENVIRONMENT (Windows Hotspot: 192.168.137.1)               |
|                                                                                    |
|  • Mosquitto MQTT Broker :1883 (TCP Localhost)                                     |
|    - bupi/internal/utterance : Mode 1 -> Mode 2 text routing                       |
|    - bupi/internal/tts       : Mode 2 -> Mode 1 speech playback                    |
|    - bupi/internal/estop     : Fleet-wide emergency stop                           |
|    - bupi/actuators/motors/cmd/json : Motor speed and duration commands            |
|                                                                                    |
|  • Unified Hardware Bridge :8767 (WebSocket 0.0.0.0)                               |
|    - 20Hz bidirectional telemetry frame streaming                                  |
|    - Node announcements & heartbeat tracking                                       |
|                                                                                    |
|  • USB Serial UART COM3 (115200 Baud)                                              |
|    - Auto-reconnecting wired hardware supervisor backup                            |
+------------------------------------------------------------------------------------+
          | (Wi-Fi 2.4GHz: 192.168.137.x)                         | (USB Cable)
          v                                                       v
+-----------------------------------+                   +----------------------------+
| Bot 1 Scout (192.168.137.x)       |                   | Bot 1 / Bot 2 Wired Backup |
| - Streams 20Hz telemetry via WS   |                   | - Serial UART Bridge       |
| Bot 2 Specialist (192.168.137.x)  |                   | - 115200 Baud JSON Frames  |
| - Streams 20Hz telemetry via WS   |                   +----------------------------+
+-----------------------------------+
```

---

## Desktop Cockpit & User Interface

The desktop UI is built **100% in Electron 41.2.1** (Chromium / Node.js):

### 1. Transparent 3D Mascot (`index.html`)
* Frameless 250x250 transparent window floating above desktop applications.
* Features a 3D animated character (`cute_character.glb`) rendered via Three.js with mouse tracking, state reactions, and pet animations.

### 2. Central Control Hub (`notepad.html`)
A 1200x800 glassmorphism tactical cockpit containing 11 specialized panels:
1. **Mode Switcher**: One-click toggle between Mode 1 (Companion) and Mode 2 (Robot).
2. **2D Tactical Arena Canvas**: Live canvas visualizing rover coordinates, sensor cones, movable obstacles, and survivor markers (`spatial_twin_2d.html`).
3. **BUPI Autonomous Panel**: Natural language mission input, scenario chips (Patrol, Find Person, Check Gas), and live mission logs.
4. **Missions & Reports**: Historical database viewer displaying debrief reports from `bupi_telemetry.db`.
5. **Hardware Setup / Ingest**: Monaco-style C++ code editor, library selector, and one-click Auto-Flash button.
6. **ESP32 Manual Control**: Manual tactile D-pad for remote driving and relay switches.
7. **Active Lab / Trained Agents**: Visual cards displaying dynamically discovered hardware agents.
8. **Chat History**: Searchable transcript logs from SQLite `bupi.db`.
9. **Notes & Ideas**: Desktop productivity notepad with local auto-save.
10. **Settings & Token Tracker**: Real-time status of LLM API keys and model rotations.
11. **System Diagnostics**: Telemetry TTL counters, hotspot status, and CPU load monitors.

---

## Repository Structure

```
c:\Users\Sachin\boopi\assistant\
├── actions/                         # Tool definitions & execution
│   ├── flasher.py                   # arduino-cli compiler & flasher
│   └── hardware_tools.py            # 17 callable agent tools & universal MQTT tool
├── agents/                          # Decision & intelligence engine
│   ├── autonomous_goal_agent.py     # 20Hz closed-loop mission engine (11 policies)
│   ├── local_orchestrator.py        # Tier 2 Ollama tool caller (~500ms)
│   ├── robotic_crew.py              # Tier 3 CrewAI multi-agent fallback
│   └── router_agent.py              # Tier 1 deterministic regex (<5ms)
├── brain/                           # Mode 1 intelligence & local stores
│   ├── ai_brain.py                  # Mode 1 streaming LLM & C++ code processor
│   ├── bupi.db                      # SQLite conversational & user memory
│   └── fts5_hardware_index.db       # SQLite FTS5 hardware knowledge index
├── bwe/                             # Bit-World Engine (Digital Twin)
│   ├── core/                        # JavaScript simulation physics engine
│   ├── interface/                   # HIL bridge connecting physical ESP32
│   └── plugins/                     # Virtual sensor & actuator plugins
├── core/                            # Core robotics algorithms
│   ├── kinematics_odometry.py       # 1.20g IMU step detection & RSSI path loss
│   ├── obstacle_bypass_engine.py    # 5-stage geometric obstacle detour
│   ├── safety_validator.py          # 15.0s TTL watchdog & gas safety barrier
│   ├── sensor_translator.py         # Raw ADC to semantic status converter
│   └── swarm_coordinator.py         # Dual-bot state fusion & hazard evacuation
├── firmware/                        # Microcontroller C++ Arduino sketches
│   ├── bupi_bot1_scout.ino          # Bot 1 Scout (HC-SR04, MPU6050, PIR)
│   └── bupi_bot2_specialist.ino     # Bot 2 Specialist (MQ-2, DHT22, HC-SR04, MPU)
├── planner/                         # Task planning
│   └── instruction_decomposer.py    # Instruction to DynamicMissionPlan compiler
├── services/                        # RAG & LLM gateways
│   ├── knowledge_super_agent.py     # Hardware knowledge RAG query engine
│   └── llm_gateway.py               # Token tracking & multi-provider rotation
├── voice/                           # Voice capture & synthesis
│   ├── listener.py                  # sounddevice + webrtcvad + Faster-Whisper
│   └── speaker.py                   # edge-tts + SAPI5 pyttsx3 fallback
├── bupi_node_server.py              # WebSocket server (:8767) & Serial COM3 bridge
├── bupi_telemetry.db                # SQLite 20Hz live telemetry database
├── hardware_memory.txt              # Dynamically learned MQTT hardware rules
├── index.html                       # Electron 3D mascot overlay
├── main.js                          # Electron main process
├── main.py                          # Python Mode 1 supervisor
├── notepad.html                     # Central Control Hub (11 tabs)
├── run_mode2.py                     # Python Mode 2 dedicated robotics daemon
├── Run_Bupi_Robot.bat               # Single-click master production launcher
└── package.json                     # Node.js dependencies
```

---

## Quick Start Guide

### Prerequisites
1. **Windows 11 PC** with Wi-Fi adapter (for Windows Mobile Hotspot).
2. **Python 3.12** with virtual environment created at `venv312`.
3. **Node.js 18+** with dependencies installed via `npm install`.
4. **Mosquitto MQTT Broker** installed and registered as a Windows service.
5. **Ollama** installed with models pulled:
   ```bash
   ollama pull llama3.2:3b
   ollama pull llama3.1:8b
   ```
6. **Arduino CLI** on system `PATH` (for dynamic C++ auto-flashing).

### Single-Click Production Launch
Double-click `Run_Bupi_Robot.bat` or execute in terminal:
```cmd
Run_Bupi_Robot.bat
```
This batch file automatically:
1. Verifies and starts the `mosquitto` service on port `1883`.
2. Starts `ollama serve` on port `11434` if not already running.
3. Runs `scripts\ensure_hotspot.ps1` to ensure the mobile hotspot is active on `192.168.137.1`.
4. Cleans up stale background processes.
5. Launches Electron (`main.js --mode 2`), which spawns Python `main.py` and `run_mode2.py`.

### Flashing Microcontrollers
To flash the physical ESP32 rovers over USB:
* **Flash Bot 1 (Scout)**: Double-click `Flash_Bot1.bat`.
* **Flash Bot 2 (Specialist)**: Double-click `Flash_Bot2.bat`.

---

## Technical Documentation Index

For complete line-by-line evidence, canonical JSON schemas, slide decks, and full audit reports, refer to the accompanying files:

* **[BUPI_MASTER_TECHNICAL_AUDIT_26201.md](file:///c:/Users/Sachin/boopi/assistant/BUPI_MASTER_TECHNICAL_AUDIT_26201.md)**: The exhaustive 25-section ground-truth audit with exact line-by-line code citations.
* **[BUPI_PPT_SLIDE_DECK_26201.md](file:///c:/Users/Sachin/boopi/assistant/BUPI_PPT_SLIDE_DECK_26201.md)**: Complete 15-slide technical presentation deck prepared for the SIH 26201 jury.
* **[BUPI_SYSTEM_ARCHITECTURE_DIAGRAMS.md](file:///c:/Users/Sachin/boopi/assistant/BUPI_SYSTEM_ARCHITECTURE_DIAGRAMS.md)**: 7 production Mermaid architecture diagrams.
* **[BUPI_CAPABILITY_SCHEMAS_AND_SPECS.md](file:///c:/Users/Sachin/boopi/assistant/BUPI_CAPABILITY_SCHEMAS_AND_SPECS.md)**: Canonical JSON schemas, telemetry packets, and device manifests.
* **[BUPI_26201_Architecture_Presentation.pptx](file:///c:/Users/Sachin/boopi/assistant/BUPI_26201_Architecture_Presentation.pptx)**: The generated 16:9 widescreen PowerPoint deck.
* **[BUPI_DATASET_FOR_PROMPTING.md](file:///c:/Users/Sachin/boopi/assistant/BUPI_DATASET_FOR_PROMPTING.md)**: Clean copy-pasteable data blocks for ChatGPT and AI tools.

---
*Created for Smart India Hackathon (SIH) Problem Statement 26201 — BUPI Robotics Platform.*
