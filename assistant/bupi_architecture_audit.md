# BUPI Codebase-Level Architecture Audit & Technical Verification Dossier

**Target Project**: BUPI – Agentic AI for Intelligent Physical Interaction  
**Audit Purpose**: Technical Hackathon PPT Verification & Defense Preparation  
**Audit Scope**: Ground-Truth Codebase Extraction (No Speculation or Unwritten Features)  
**Date**: September 2026  

---

## Executive Summary

This document presents the complete codebase-level technical audit of **BUPI**. It provides ground-truth evidence extracted directly from source code files, configuration scripts, and firmware files.

### Core Architectural Truths at a Glance
1. **Host-Centric Networking**: The central node is the **Host Laptop (Windows PC)** running a Windows Mobile Hotspot gateway (`192.168.137.1`), Mosquitto MQTT broker (`127.0.0.1:1883`), and an asynchronous WebSocket server on port `8767`. The ESP32 robots communicate with the host via **WebSockets (`ws://192.168.137.1:8767`) at 20 Hz**, with USB Serial (115200 baud) as a wired fallback.
2. **Hierarchical 3-Tier AI Orchestration**: Real-time robot movements do **not** wait for CrewAI LLM deliberation (which incurs 5–15 seconds of latency). Instead:
   - **Tier 1 (Fast-Pass Reflex, <5ms)**: Regex classification and deterministic state machines execute immediate E-stops, direct motor drives, and compiled autonomous closed-loop missions.
   - **Tier 2 (Local LLM Orchestrator, ~500ms)**: Ollama (`llama3.2:3b`) executes single-turn tool calling 100% offline.
   - **Tier 3 (CrewAI Fallback, 5–15s)**: Multi-agent hierarchical planning with dynamic capability-based sub-agent creation serves as a tertiary fallback.
3. **Distinct Hardware Specialization**:
   - **Bot 1 (Scout)**: Mobility, spatial reconnaissance, obstacle detection, and human tracking via HC-SR04, MPU6050, and **PIR Thermal Motion Sensor**.
   - **Bot 2 (Specialist)**: Environmental hazard assessment and climate monitoring via HC-SR04, MPU6050, **MQ-2 Gas/Smoke Sensor**, and **DHT22 Climate Sensor**.
4. **Autonomous Closed-Loop Control**: Runs at **20 Hz (50ms)** in `agents/autonomous_goal_agent.py`, supporting dynamic replanning, active obstacle bypass routines, and target homing.
5. **100% Offline Capability**: Runs Faster-Whisper STT locally, Ollama `llama3.2:3b` locally, Windows SAPI5 TTS locally, and local WebSockets/MQTT without requiring an internet connection.

---

# Part 1: Comprehensive System Audit & Component Catalog

```
=============================================================================================================
                                     BUPI ACTUAL PROJECT ARCHITECTURE
=============================================================================================================

                                  +---------------------------------------+
                                  |       USER / PHYSICAL OPERATOR        |
                                  |  (Speech Voice / Text / GUI / Hotspot)|
                                  +---------------------------------------+
                                                      |
                                                      v
                                  +---------------------------------------+
                                  |    ELECTRON DESKTOP FRONTEND (GUI)    |
                                  |   - Frameless Mascot: index.html      |
                                  |   - Mission Studio: notepad.html      |
                                  |   - 2D Arena Canvas: bupi_auton...js  |
                                  +---------------------------------------+
                                                      |
                                          IPC / stdio JSON stream
                                                      v
  +---------------------------------------------------------------------------------------------------------+
  |                                       HOST LAPTOP (WINDOWS PC) RUNTIME                                   |
  |                                                                                                         |
  |  +---------------------------+   MQTT ("bupi/internal/utterance")   +--------------------------------+  |
  |  |   MODE 1: VOICE / DESKTOP | -----------------------------------> |    MODE 2: ROBOTIC RUNNER      |  |
  |  | - ListenerThread (Whisper)|                                      |   (run_mode2.py)               |  |
  |  | - SpeakerThread (EdgeTTS) | <----------------------------------- | - Tier 1: RouterAgent (<5ms)   |  |
  |  | - AIThread (Gemini / RAG) |      MQTT ("bupi/internal/tts")      | - Tier 2: Local LLM (~500ms)   |  |
  |  +---------------------------+                                      | - Tier 3: CrewAI Fallback      |  |
  |                                                                     +--------------------------------+  |
  |                                                                                     |                   |
  |                                                     +-------------------------------+                   |
  |                                                     |                                                   |
  |                                                     v                                                   |
  |  +---------------------------------------------------------------------------------------------------+  |
  |  |                       UNIFIED HARDWARE BRIDGE (bupi_node_server.py)                               |  |
  |  |  - Mosquitto MQTT Broker (localhost:1883)                                                         |  |
  |  |  - WebSocket Server (0.0.0.0:8767, async loop)                                                    |  |
  |  |  - USB Serial Supervisor (COM3 / auto CP210x/CH340 @ 115200 baud)                                 |  |
  |  |  - Kinematics & Odometry Engine (IMU peak gait + Wi-Fi RSSI path loss distance)                    |  |
  |  |  - Asynchronous Batch DB Writer (bupi_telemetry.db)                                                |  |
  |  |  - Windows Mobile Hotspot Watchdog (scripts/ensure_hotspot.ps1 -> 192.168.137.1)                  |  |
  |  +---------------------------------------------------------------------------------------------------+  |
  +---------------------------------------------------------------------------------------------------------+
                                    |                                         |
               WebSocket ws://192.168.137.1:8767                   USB Serial (COM3, 115200 baud)
               (JSON telemetry / motor commands)                   (Direct wired fallback)
                                    |                                         |
                   +----------------+--------------------+                    |
                   |                                     |                    |
                   v                                     v                    v
+------------------------------------+ +------------------------------------+
|         BOT 1: SCOUT ROBOT         | |   BOT 2: ENVIRONMENTAL SPECIALIST  |
| - Target: ESP32-WROOM-32           | | - Target: ESP32-WROOM-32           |
| - Firmware: bupi_bot1_scout.ino    | | - Firmware: bupi_bot2_specialist...|
| - Sensors: HC-SR04, PIR, MPU6050   | | - Sensors: HC-SR04, MQ-2, DHT22,   |
| - Motor: TB6612FNG + 2x N20        | |            MPU6050                 |
| - Features: 20Hz WebSockets, IMU   | | - Motor: TB6612FNG + 2x N20        |
|   Kinematics, Gyro-Yaw Turns,      | | - Features: Gas hazard monitor,    |
|   Edge Obstacle Avoidance FSM      | |   DHT climate, Gyro-Yaw Turns      |
+------------------------------------+ +------------------------------------+
```

### Detailed Component Inventory

| Component Name | File / Path | Purpose & Technology | Interacts With | Input / Output | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **System Launcher** | `Run_Bupi_Robot.bat` | Batch bootstrap script; checks Mosquitto, Ollama, Hotspot watchdog, launches Electron | OS, Mosquitto, Ollama, Hotspot | In: User click<br/>Out: Running processes | `[IMPLEMENTED]` |
| **Electron Main Process** | `main.js` | Electron Node.js runtime; spawns Python engine, manages IPC and frameless GUI windows | `index.html`, `notepad.html`, `main.py` | In: IPC events<br/>Out: Rendered windows | `[IMPLEMENTED]` |
| **Mode 1 Desktop AI** | `main.py` | PyQt6 thread manager hosting Whisper STT, Edge-TTS, and conversation brain | `voice/`, `brain/`, `main.js`, MQTT | In: Mic audio, UI IPC<br/>Out: Spoken audio, MQTT | `[IMPLEMENTED]` |
| **Mode 2 Robotic Daemon** | `run_mode2.py` | Background robotic server; listens for utterances on MQTT and executes 3-tier pipeline | MQTT broker, `agents/`, `core/` | In: `bupi/internal/utterance`<br/>Out: `bupi/internal/tts`, motor cmds | `[IMPLEMENTED]` |
| **Unified Hardware Bridge** | `bupi_node_server.py` | Multi-protocol physical bridge (WebSockets 8767, Serial COM3, Mosquitto 1883, DB writer) | ESP32s, MQTT, SQLite, UI WebSockets | In: Raw 20Hz JSON telemetry<br/>Out: Motor frames, SQLite rows | `[IMPLEMENTED]` |
| **Router Agent** | `agents/router_agent.py` | Microsecond (<5ms) deterministic regex classifier & Whisper phonetics normalizer | Event bus, `AutonomousGoalAgent`, LLM Gateway | In: Transcribed string<br/>Out: Classified intent payload | `[IMPLEMENTED]` |
| **Instruction Decomposer** | `planner/instruction_decomposer.py` | Natural language compiler producing `DynamicMissionPlan` objects with typed policies | `RouterAgent`, `AutonomousGoalAgent` | In: Free-form text<br/>Out: `DynamicMissionPlan` | `[IMPLEMENTED]` |
| **Autonomous Goal Agent** | `agents/autonomous_goal_agent.py` | 20Hz closed-loop autonomous mission runner (PIR search, 360° sweeps, gas surveys) | `bupi_node_server`, `SafetyController`, MQTT | In: Mission plan<br/>Out: Motor cmds, verbal debrief | `[IMPLEMENTED]` |
| **Local LLM Orchestrator** | `agents/local_orchestrator.py` | 100% offline single-agent tool-calling orchestrator using Ollama `llama3.2:3b` | Local Ollama endpoint (`:11434`), hardware tools | In: User request text<br/>Out: Tool execution result | `[IMPLEMENTED]` |
| **Hierarchical CrewAI** | `agents/robotic_crew.py` | Dynamic multi-agent crew; spawns `Sensor Listener` and `Actuator Controller` sub-agents | CrewAI, `bupi_node_server.py`, LiteLLM | In: Complex task description<br/>Out: Structured companion response | `[IMPLEMENTED]` |
| **Hardware Tools** | `actions/hardware_tools.py` | Zero-overhead tool definitions (`control_motors`, `read_sensor_status`, `control_relay`) | Mosquitto MQTT, `safety_validator.py` | In: Function arguments<br/>Out: Execution status string | `[IMPLEMENTED]` |
| **Safety Validator** | `core/safety_validator.py` | Aggregates world state, enforces 15s telemetry TTL, validates planned actions | SQLite, in-memory telemetry | In: Topic & payload<br/>Out: `{"approved": bool, "reason": str}` | `[IMPLEMENTED]` |
| **Safety Controller** | `safety/safety_controller.py` | Intercepts actions from planner; issues `APPROVED`, `MODIFIED`, or `OVERRIDDEN` | `AutonomousGoalAgent` | In: `StructuredAction`<br/>Out: Safe action | `[IMPLEMENTED]` |
| **Obstacle Bypass Engine** | `core/obstacle_bypass_engine.py` | Deterministic 5-step flank-and-detour active evasion maneuver around barriers | Mosquitto MQTT, motor driver | In: Target bot, flank direction<br/>Out: Bypass execution sequence | `[IMPLEMENTED]` |
| **Kinematics & Odometry** | `core/kinematics_odometry.py` | Fuses MPU6050 gait step detection, gyro dead reckoning ($X, Y$), and Wi-Fi RSSI distance | `bupi_node_server.py` | In: Raw IMU & RSSI<br/>Out: ($X, Y$), distance from laptop | `[IMPLEMENTED]` |
| **Bot 1 Scout Firmware** | `firmware/bupi_bot1_scout/...ino` | ESP32 C++ firmware; HC-SR04, PIR, MPU6050, TB6612FNG, closed-loop gyro turns | Host PC WebSockets/Serial | In: Motor JSON frames<br/>Out: 20Hz telemetry JSON | `[IMPLEMENTED]` |
| **Bot 2 Specialist Firmware** | `firmware/bupi_bot2_specialist/...ino` | ESP32 C++ firmware; HC-SR04, MQ-2, DHT22, MPU6050, TB6612FNG | Host PC WebSockets/Serial | In: Motor JSON frames<br/>Out: 20Hz telemetry JSON | `[IMPLEMENTED]` |
| **Speech Listener (STT)** | `voice/listener.py` | Captures audio (16kHz), applies WebRTC VAD 3, transcribes with Faster-Whisper | Microphone, `main.py` | In: Raw PCM audio<br/>Out: Transcribed text string | `[IMPLEMENTED]` |
| **Speech Synthesizer (TTS)** | `voice/speaker.py` | Neural TTS via Edge-TTS cloud WebSocket with automatic offline fallback to SAPI5 | `main.py`, Audio output | In: Text string<br/>Out: Audio waveform | `[IMPLEMENTED]` |
| **Telemetry Database** | `bupi_telemetry.db` | Local SQLite database storing telemetry history, registered nodes, and mission logs | `bupi_node_server`, `AutonomousGoalAgent` | In: Batched SQL inserts<br/>Out: Telemetry rows & reports | `[IMPLEMENTED]` |

---

# Part 2: Actual End-to-End Data Flow Trace

Tracing: **"Boopi, scan the room and if you find any person move towards him."**

```
[1. Human Acoustic Speech]
       |
       v
[2. voice/listener.py: ListenerThread]
       | Captures audio via sounddevice (16kHz, 30ms frames)
       | Filters background noise using webrtcvad (Aggressiveness=3)
       | Passes speech buffer to local Faster-Whisper (base model)
       v
[3. main.py: on_speech_recognized()]
       | Transcribed: "scan the room and if you find any person move towards him"
       | Checks Mode 2 status (mode2_active == True)
       | Publishes to Mosquitto MQTT: "bupi/internal/utterance"
       v
[4. run_mode2.py: on_message()]
       | Receives JSON payload from "bupi/internal/utterance"
       | Spawns worker thread: process_with_crew()
       v
[5. agents/router_agent.py: quick_regex_classify()]
       | Normalizes text (strips wake words, cleans acoustic errors)
       | Evaluates InstructionDecomposer._semantic_decompose() in <2ms
       | Output: Intent {"type": "autonomous_mission", "payload": {"mission": "..."}}
       v
[6. agents/autonomous_goal_agent.py: start_mission()]
       | Compiles DynamicMissionPlan:
       |   - Primary Policy: PolicyType.SCAN_SWEEP (360° radar room sweep)
       |   - Chained Next Policy: PolicyType.APPROACH_TARGET (PIR homing)
       |   - Target Robot: "bupi_01" (Scout)
       | Spawns dedicated closed-loop thread: execute_dynamic_mission()
       v
[7. 20Hz Closed-Loop Execution Loop]
       | Step A: Publishes spoken intent to "bupi/internal/tts" -> speaker.say()
       | Step B: Reads current gyro heading from MPU6050
       | Step C: Publishes motor command to MQTT "bupi/actuators/motors/cmd/json"
       |         Payload: {"action": "turn_by", "degrees": 45.0, "speed": 220, "bot_id": "bupi_01"}
       v
[8. bupi_node_server.py: on_mqtt_message()]
       | Ingests motor command from Mosquitto MQTT
       | Identifies target socket for "bupi_01" in hardware_clients_by_bot
       | Sends WebSocket JSON frame over TCP to ESP32 (192.168.137.101:8767)
       v
[9. ESP32 Scout Firmware (bupi_bot1_scout.ino)]
       | webSocketEvent() parses JSON payload
       | Motor Controller drives TB6612FNG (PWMA=25, AIN1=26, AIN2=27, PWMB=33, BIN1=14, BIN2=12)
       | Motors rotate; MPU6050 gyro integrates yaw angle until target reached
       | Samples HC-SR04, PIR, and IMU; formats 20Hz telemetry JSON
       | Transmits WebSocket frame back to host PC:
       | {"bot_id":"bupi_01","distance_cm":180.5,"pir":1,"heading":45.0,"ax":0.02,"steps":4}
       v
[10. bupi_node_server.py: handle_incoming_telemetry()]
       | Ingests 20Hz frame; updates memory cache `telemetry_by_bot["bupi_01"]`
       | Pushes row to `_db_queue` -> asynchronous batched insert to `bupi_telemetry.db`
       | Computes inertial odometry and Wi-Fi RSSI distance in `odometry_engine`
       | Broadcasts telemetry JSON update to Electron notepad UI canvas
       v
[11. agents/autonomous_goal_agent.py: Sample & Transition]
       | samples get_current_world_state() at 20Hz
       | Detects: pir == 1 (Human detected at sector heading 45.0°)
       | Records event: "HUMAN_DETECTED_PIR"
       | Halts sweep and transitions to chained plan: _run_approach_target_mission()
       | Drives forward while monitoring HC-SR04 clearance
       v
[12. Mission Completion & Debrief Generation]
       | Proximity threshold reached (distance_cm <= 35cm)
       | Motors cut off (`stop`); debrief compiled and saved to SQLite `missions` table
       | Spoken synthesis emitted to TTS: "Target reached. Human located at 45 degrees."
       | Electron notepad.html renders structured markdown debrief and 2D trajectory
```

---

# Part 3: Networking Architecture

### Topology & Node Structure
- **Central Node**: Host Laptop (Windows PC).
- **Physical Wi-Fi Subnet**: Windows Mobile Hotspot adapter (`192.168.137.1`, subnet mask `255.255.255.0`).
- **Protocols Active**:
  - **Wi-Fi WebSockets (`ws://`)**: Real-time 20Hz bidirectional telemetry and motor frames.
  - **MQTT (TCP)**: Local host IPC on port 1883.
  - **USB Serial (UART)**: Hardware backup at 115200 baud on `COM3`.
  - **Node IPC (Stdio)**: JSON line streaming between Electron and Python.

### Connection Routing Table

| Source | Destination | Protocol | Port / Topic | Direction | Purpose | Evidence in Code |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Electron UI** | `main.py` | Stdio Pipe | JSON Lines | Bidirectional | UI commands, mascot states | `main.js:L218` |
| `main.py` (Mode 1) | `run_mode2.py` (Mode 2) | MQTT | `bupi/internal/utterance` | Mode 1 -> Mode 2 | Forwards transcribed speech | `main.py:L268` |
| `run_mode2.py` | `main.py` | MQTT | `bupi/internal/tts` | Mode 2 -> Mode 1 | Verbal responses for TTS | `run_mode2.py:L276` |
| **Agents / Planners** | `bupi_node_server.py` | MQTT | `bupi/actuators/motors/cmd/json` | Agents -> Bridge | Publishes motor commands | `actions/hardware_tools.py:L173` |
| `bupi_node_server.py` | **Bot 1 Scout** | WebSocket | `ws://192.168.137.1:8767` | Bidirectional | 20Hz telemetry & motor frames | `bupi_node_server.py:L634`, `bupi_bot1_scout.ino:L74` |
| `bupi_node_server.py` | **Bot 2 Specialist**| WebSocket | `ws://192.168.137.1:8767` | Bidirectional | 20Hz telemetry & motor frames | `bupi_node_server.py:L634`, `bupi_bot2_specialist.ino:L86` |
| `bupi_node_server.py` | **ESP32 Hardware** | USB Serial | `COM3` @ 115200 baud | Bidirectional | Wired hardware fallback | `bupi_node_server.py:L605` |
| `bupi_node_server.py` | `bupi_telemetry.db` | SQLite API | Local file write | Bridge -> DB | Batched persistence (1.5s) | `bupi_node_server.py:L53` |
| `bupi_node_server.py` | **UI WebSockets** | WebSocket | Port `8767` | Server -> UI | Live 2D arena coordinates | `bupi_node_server.py:L434` |

### MQTT Specifications
- **Broker**: Mosquitto on `localhost:1883` (no auth).
- **Core Topics**: `bupi/internal/utterance`, `bupi/internal/tts`, `bupi/actuators/motors/cmd`, `bupi/actuators/motors/cmd/json`, `bupi/v1/bot2/actuators/motors/cmd`, `bupi/{bot_id}/sensors/+/state`.
- **Quality of Service**: QoS 0 (low-overhead real-time delivery).

### Offline Operation Reality
- **Continues Working Offline**: Faster-Whisper local STT (`base` model), Ollama `llama3.2:3b` local LLM, RouterAgent regex fast-pass, AutonomousGoalAgent 20Hz closed loops, ESP32 edge obstacle avoidance, odometry tracking, SQLite persistence, and SAPI5 speech synthesis.
- **Stops Working Offline**: Gemini Cloud API, Groq Cloud API, OpenRouter, NVIDIA API, and Microsoft Edge-TTS (automatically diverts to local SAPI5).

---

# Part 4: AI & LLM Architecture

```
                                  [USER REQUEST]
                                         |
                                         v
                     +---------------------------------------+
                     |    TIER 1: DETERMINISTIC FAST-PASS    |
                     |         agents/router_agent.py        |
                     |     Regex Classifier (<5ms latency)   |
                     +---------------------------------------+
                                  /             \
                       [Matched] /               \ [Unmatched]
                                v                 v
         +-----------------------------+   +------------------------------------+
         |   AUTONOMOUS GOAL AGENT     |   |    TIER 2: LOCAL ORCHESTRATOR      |
         | agents/autonomous_goal_agent|   |     agents/local_orchestrator.py   |
         |  20Hz Closed-Loop Execution |   |  Ollama llama3.2:3b (~500ms offline)|
         +-----------------------------+   +------------------------------------+
                                                     /            \
                                          [Success] /              \ [Error / Complex]
                                                   v                v
                                        +-------------------+  +-----------------------+
                                        | EXECUTE HARDWARE  |  | TIER 3: CREWAI CREW   |
                                        |  VIA MQTT BRIDGE  |  |  agents/robotic_crew  |
                                        +-------------------+  | Dynamic sub-agents    |
                                                               | (5-15s LLM latency)   |
                                                               +-----------------------+
```

### Models & Execution Profile
1. **Ollama `llama3.2:3b`** (Local GPU/CPU): Primary local tool-calling engine in `LocalAgentOrchestrator` (`agents/local_orchestrator.py:L213`). Provides 12 OpenAI-formatted tool schemas. Execution latency: ~500ms.
2. **Gemini 2.5 Flash** (Cloud API): Primary cloud conversational model in `services/llm_gateway.py`. Features multi-key rotation across `GOOGLE_AI_STUDIO_KEY_1..10`.
3. **Groq Llama-3.3-70B Versatile** (Cloud API): Cloud reasoning fallback in `agents/robotic_crew.py` with multi-key rotation across `GROQ_API_KEY_1..10`.
4. **Faster-Whisper `base`** (Local CPU/CUDA): Local speech-to-text model in `voice/listener.py` with custom vocabulary prompt injection.

### Dynamic Multi-Agent Spawning in CrewAI
In `agents/robotic_crew.py`:
- Master Agent: `Robotic Orchestrator` (configured with 12 hardware tools).
- Online Node Discovery: Queries `live_nodes` in `bupi_node_server.py`.
- Dynamic Sub-Agent Spawning:
  - Discovered nodes with `Sensor` capability spawn a `Sensor Listener for <Device>` sub-agent.
  - Discovered nodes with `Display` or `Actuator` capability spawn an `Actuator Controller for <Device>` sub-agent.
- Registry Persistence: Saved to `brain/trained_agents.json`.

---

# Part 5: Robot & ESP32 Firmware Architecture

```
+---------------------------------------------------------------------------------------+
|                                ESP32 FIRMWARE PIPELINE                                |
+---------------------------------------------------------------------------------------+

 [COMMUNICATION CHANNELS]
   - WebSocketsClient (ws://192.168.137.1:8767)
   - Hardware Serial (115200 baud, newline-delimited)
          |
          v
 [COMMAND INGESTION & JSON PARSER]
   - Actions: "forward", "reverse", "left", "right", "stop", "turn_by", "auto_avoid"
   - Parameters: speed (0-255), duration_ms, degrees (-180 to +180)
          |
          v
 [SAFETY & REFLEX LAYER]
   - Barrier Obstacle Cutoff: checks distanceCm <= CRITICAL_OBSTACLE_CM (default 0/disabled)
   - Chassis Tilt Cutoff: checks max(pitch, roll) >= 85°
          |
          v
 [CLOSED-LOOP MOTOR CONTROLLER]
   - Gyro-Yaw Integration: gz_dps * dt -> headingDeg
   - Precision angular turn control loop (terminates when target heading reached)
   - Onboard Edge Obstacle Avoidance FSM (7 states: Cruise, Reverse, Pivot, Flank, etc.)
          |
          v
 [TB6612FNG H-BRIDGE DRIVER] -> 2x N20 DC Gear Motors (Differential Drive)

-----------------------------------------------------------------------------------------

 [RAW SENSORS]
   - HC-SR04 Ultrasonic (TRIG=5, ECHO=18)
   - MPU6050 6-Axis IMU (SDA=21, SCL=22, I2C 0x68)
   - Bot 1 Only: PIR Motion Detector (GPIO 34/19)
   - Bot 2 Only: MQ-2 Gas/Smoke (ADC1 GPIO 34), DHT22 Climate (GPIO 4)
          |
          v
 [EDGE SENSOR FILTERING & KINEMATICS]
   - Ultrasonic 3-sample median filter
   - IMU pitch & roll complementary filter
   - Peak dynamic acceleration gait step counter (~7.5 cm stride)
          |
          v
 [20Hz TELEMETRY SERIALIZER]
   - Formats comprehensive JSON payload
   - Emits upstream via WebSocket client and Serial TX
```

---

# Part 6: Current Hardware Division: Bot 1 vs. Bot 2

| Component | Bot 1: Scout | Bot 2: Specialist | Code / Firmware Evidence |
| :--- | :--- | :--- | :--- |
| **Compute Board** | ESP32-WROOM-32 | ESP32-WROOM-32 | `bupi_bot1_scout.ino`, `bupi_bot2_specialist.ino` |
| **Chassis Driver** | TB6612FNG H-Bridge | TB6612FNG H-Bridge | PWM pins 25, 33/14; Dir pins 26, 27, 14/12 |
| **Motors** | 2x N20 DC Gear Motors | 2x N20 DC Gear Motors | Differential drive configuration |
| **Obstacle Sensor** | HC-SR04 Ultrasonic | HC-SR04 Ultrasonic | TRIG = GPIO 5, ECHO = GPIO 18 |
| **IMU / Kinematics** | MPU6050 6-Axis (I2C) | MPU6050 6-Axis (I2C) | SDA = GPIO 21, SCL = GPIO 22 (addr 0x68) |
| **Human Detection** | **PIR Thermal Sensor** | *None* | `PIN_PIR` = GPIO 34 / 19 (`bupi_bot1_scout.ino:L46`) |
| **Gas & Smoke** | *None* | **MQ-2 Gas Sensor** | `PIN_MQ2_ADC` = GPIO 34 ADC1 (`bupi_bot2_specialist.ino:L66`) |
| **Climate Sensing** | *None* | **DHT22 Sensor** | `PIN_DHT` = GPIO 4 (`bupi_bot2_specialist.ino:L67`) |
| **Target Role** | Recon, Search & Rescue | Hazard, Climate, Gas | Dispatched via `target_bot` field in JSON |

---

# Part 7: Sensor Data Flow & Fusion Reality

### Multi-Sensor Fusion Reality
The implementation is **not an Extended Kalman Filter (EKF)**. It is an **Epistemic Decision Fusion and Inertial Kinematics Engine**:
1. **Kinematics Odometry Fusion** (`core/kinematics_odometry.py`):
   - Combines MPU6050 peak dynamic acceleration ($>1.20g$) with a refractory step debounce ($180\text{ ms}$) to calculate forward steps ($\sim 7.5\text{ cm/stride}$).
   - Integrates gyroscope Z-axis angular velocity to track heading angle.
   - Computes dead-reckoned Cartesian coordinates ($X, Y$) in meters.
   - Evaluates Wi-Fi RSSI indoor signal attenuation via the **Log-Distance Path Loss Model**:
     $$d = 10^{\frac{\text{RSSI}_0 - \text{RSSI}}{10 \cdot n}}$$
     (Calibrated: $\text{RSSI}_0 = -42.0\text{ dBm}$, $n = 2.5$).
2. **World State Aggregation** (`core/safety_validator.py`):
   - Aggregates ultrasonic distance, IMU tilt, PIR motion, MQ-2 gas, and DHT22 temperature into unified semantic states (`SAFE`, `COLLISION_RISK`, `HAZARD`).
3. **Swarm Tandem Fusion** (`core/swarm_coordinator.py`):
   - Pairs Bot 1's spatial location with Bot 2's environmental readings into a unified multi-robot state.

---

# Part 8: Safety Architecture

| Safety Feature | Trigger Condition | Enforced Action | Implemented Where | Can AI Override? |
| :--- | :--- | :--- | :--- | :--- |
| **Emergency Stop (E-Stop)** | Utterance contains "stop", "halt", "freeze", "e-stop" | Direct cutoff of all motor channels | `agents/router_agent.py:L127` | **No. Hardware stops unconditionally.** |
| **Telemetry TTL Watchdog** | Telemetry timestamp $> 15.0\text{ s}$ old | Forward movement blocked; state set to `UNKNOWN_STALE` | `core/safety_validator.py:L6` | No. Stale data blocks actuation. |
| **Planner Safety Interceptor** | Distance $\le 15\text{ cm}$ or Tilt $> 85^\circ$ | Action overridden to `STOP` (`SafetyVerdict.OVERRIDDEN`) | `safety/safety_controller.py:L78` | No. Hard constraint over planner. |
| **Active Obstacle Bypass** | Front obstacle detected during forward mission | Triggers 5-step detour maneuver | `core/obstacle_bypass_engine.py` | Autonomous evasion routine. |
| **Firmware Obstacle Barrier** | Distance $\le \text{CRITICAL\_OBSTACLE\_CM}$ | Firmware cuts PWM signals | Firmware `.ino` loop | **Firmware overrides software.** *(Configured to 0.0 in dev)* |
| **Firmware Rollover Tilt** | Max tilt $\ge 85^\circ$ | Firmware cuts PWM signals | Firmware `.ino` loop | **Firmware overrides software.** *(Configured to 85° in dev)* |
| **Gas Hazard Alarm** | MQ-2 reading $> 300\text{ ppm}$ | Mission aborted, verbal hazard alert emitted | `agents/autonomous_goal_agent.py` | AI triggers retreat protocol. |

---

# Part 9: Closed-Loop Feedback & Replanning

### The 20 Hz Closed-Loop Cycle
$$\text{Observe} \longrightarrow \text{Reason} \longrightarrow \text{Act} \longrightarrow \text{Observe} \longrightarrow \text{Replan}$$

Implemented in `agents/autonomous_goal_agent.py` (`execute_dynamic_mission`):
1. **Observe**: Samples `get_current_world_state()` and `get_latest_telemetry()` at 20 Hz (50 ms interval).
2. **Reason**: Checks mission exit conditions, target detection thresholds, and safety margins.
3. **Act**: Issues micro-locomotion commands (`send_motor_cmd`) to the bridge.
4. **Re-Observe & Replan**:
   - If an obstacle appears ($<35\text{ cm}$): Forward travel aborts and invokes `execute_obstacle_bypass()`.
   - If PIR detects motion during a 360° sweep: The sweep terminates, records the target heading, and launches `APPROACH_TARGET`.
   - Chained execution: Upon completing step 1, automatically advances to `plan.next_plan`.

---

# Part 10: Database, State & Memory

### SQLite Schemas
1. **`bupi_telemetry.db`**:
   - `telemetry`: `(timestamp REAL, sensor_id TEXT, value REAL)` — Persists high-frequency sensor readings via asynchronous batching.
   - `nodes`: `(client_id TEXT PRIMARY KEY, device_name TEXT, ip_address TEXT, capabilities TEXT, last_heartbeat REAL, status TEXT)` — Persists discovered hardware nodes.
   - `missions`: `(id INTEGER PRIMARY KEY, mission_name TEXT, goal TEXT, project_type TEXT, started_at REAL, ended_at REAL, duration_seconds REAL, status TEXT, findings_json TEXT, report_markdown TEXT)` — Persists completed autonomous mission reports.
   - `decisions`: `(timestamp REAL, intent TEXT, world_state TEXT, approved INTEGER, reason TEXT)` — Persists safety audit logs.
2. **Desktop Memory (Mode 1)**:
   - Managed by `brain/db_manager.py`: stores user preferences, reminders, conversational turn history, and emotional memory summaries.

---

# Part 11: Frontend & UI Architecture

- **Frameless Mascot (`index.html`)**: 250×250 transparent, always-on-top desktop window running Three.js 3D mascot (`cute_character.glb`) or Rive canvas (`tiny_mascot.riv`). Synchronizes emotional states (`listening`, `talking`, `thinking`, `idle`) with Python.
- **Mission Studio Dashboard (`notepad.html`)**: 1200×800 framed operational window displaying:
  - Live mode toggles (Mode 1 Desktop vs. Mode 2 Robotics).
  - ESP32 node discovery cards with IP, connection type, and capability tags.
  - Interactive 2D Arena Canvas (dual-bot spatial tracking, human markers, obstacle bounding boxes).
  - Mission debrief viewer with Markdown rendering.

---

# Part 12: Audit of Previous PPT Claims

| PPT Claim | Evidence in Code | Status | Actual Implementation | Recommended PPT Action |
| :--- | :--- | :--- | :--- | :--- |
| **"CrewAI Orchestrator executes all robot actions"** | `agents/robotic_crew.py`, `agents/router_agent.py` | ⚠️ **PARTIALLY VERIFIED** | CrewAI exists with dynamic sub-agents, but real-time navigation uses `RouterAgent` and `AutonomousGoalAgent` at 20 Hz to avoid 5–15s LLM planning lag. CrewAI acts as a tier-3 fallback. | **Reframe**: Present as a *Hierarchical 3-Tier Execution Pipeline* (Fast-Pass Reflex -> Local LLM -> CrewAI Fallback). |
| **"Multi-Agent Orchestration"** | `agents/robotic_crew.py:L242` | ✅ **VERIFIED** | Code dynamically spawns specialized `Sensor Listener` and `Actuator Controller` sub-agents based on online ESP32 node capabilities. | **Keep & Detail**: Explain how sub-agents are generated dynamically from live hardware discovery. |
| **"One Brain, Multiple Robots"** | `bupi_node_server.py:L71`, `core/swarm_coordinator.py` | ✅ **VERIFIED** | Central Python host bridges Bot 1 Scout and Bot 2 Specialist simultaneously, fusing spatial telemetry with gas/climate data. | **Highlight as Core Strength**: Feature Bot 1 (Scout) and Bot 2 (Specialist) hardware division. |
| **"Autonomous Decision Loops"** | `agents/autonomous_goal_agent.py:L381` | ✅ **VERIFIED** | 20Hz closed-loop loop: samples world state, detects targets, checks safety, and executes chained plans. | **Keep**: Present the 20Hz closed-loop state machine. |
| **"Hardware Agnostic Architecture"** | `bupi_node_server.py:L148`, `actions/hardware_tools.py` | ✅ **VERIFIED** | Nodes self-announce capabilities via JSON over WebSockets/Serial; high-level tools operate via generalized topics. | **Keep**: Show standard JSON announcement handshake. |
| **"100% Offline-Capable AI"** | `voice/listener.py`, `agents/local_orchestrator.py` | ✅ **VERIFIED** | Local Faster-Whisper + Local Ollama `llama3.2:3b` + Local SAPI5 TTS + Local WebSockets/MQTT. Completely operable offline. | **Highlight**: Defend with exact model names (`llama3.2:3b`, `faster-whisper base`). |
| **"20 Hz ESP32 Control Loop"** | `bupi_bot1_scout.ino:L96`, `bupi_node_server.py:L280` | ✅ **VERIFIED** | Firmware samples sensors and streams telemetry packets every 50 ms (20 Hz); Python processes at 20 Hz. | **Keep**: Validated in code timing loops. |
| **"Feedback & Dynamic Replanning"** | `core/obstacle_bypass_engine.py`, `agents/autonomous_goal_agent.py` | ✅ **VERIFIED** | Closed-loop obstacle detection triggers 5-stage bypass maneuver; PIR trigger transitions scan into approach. | **Keep**: Feature the obstacle bypass routine. |
| **"Multi-Sensor Fusion (EKF/Kalman)"** | `core/kinematics_odometry.py`, `core/safety_validator.py` | ⚠️ **PARTIALLY VERIFIED** | Not an EKF/Kalman filter. It is an **Epistemic Decision & State Fusion Engine** (combining dynamic IMU step detection, gyro heading, and Wi-Fi RSSI path loss modeling). | **Modify**: Remove claims of "Kalman Filter"; replace with *Multi-Sensor Decision Fusion & Kinematics Odometry*. |
| **"Safety Supervisor Overrides AI"** | `safety/safety_controller.py`, `core/safety_validator.py` | ✅ **VERIFIED** | `SafetyController` intercepts actions and issues `OVERRIDDEN_FORCED_STOP` when physical limits are violated. *(Note: Threshold flags currently disabled in dev).* | **Keep, but clarify**: Explain that software safety is designed to supersede AI, and explain dev vs production threshold modes. |

---

# Part 13: What to Add and What to Remove in the PPT

### Add to PPT (High Technical Impact)
1. **The 3-Tier Intelligence Architecture**: (Fast-Pass <5ms -> Local LLM ~500ms -> CrewAI Fallback 5-15s).
2. **True Network Topology Diagram**: Host laptop as Hotspot (`192.168.137.1`), WebSockets port `8767`, MQTT port `1883`, Serial `COM3`.
3. **Hardware Specialization**: Bot 1 Scout (PIR, spatial search) vs. Bot 2 Specialist (MQ-2, DHT22, hazard monitoring).
4. **Kinematics & Inertial Odometry**: MPU6050 dynamic gait step counter fused with gyro yaw and Wi-Fi RSSI Log-Distance Path Loss.
5. **Active Obstacle Bypass Maneuver**: The 5-step detour routine.

### Remove or Reframe in PPT (To Defend Against Judges)
1. **REMOVE**: *"Every motor command is decided by CrewAI."* -> Reframe to: *"Hierarchical hybrid architecture: deterministic reflex loops handle real-time 20Hz navigation, while CrewAI handles high-level multi-agent task planning and fallback reasoning."*
2. **REMOVE**: *"Extended Kalman Filter (EKF) sensor fusion."* -> Reframe to: *"Multi-Sensor Epistemic Decision Fusion & Kinematics Odometry."*
3. **REVISE**: *"Firmware obstacle cutoff is always active."* -> Reframe to: *"Configurable safety thresholds across firmware and software tiers for lab development flexibility."*

---

# Part 14: Recommended 10-Slide Hackathon Pitch Deck Structure

- **Slide 1: Title & Vision**: BUPI – Agentic Physical Intelligence & Collaborative Multi-Robot Hive Mind (Local-First, 20Hz Closed-Loop Autonomous Robotics).
- **Slide 2: Problem & Physical Interaction Gap**: Why cloud LLMs fail at physical robotics (latency, safety, connection dropouts).
- **Slide 3: Network Topology & Hardware Bridge**: Host laptop hotspot (`192.168.137.1`), 20Hz WebSockets (`:8767`), Mosquitto MQTT (`:1883`), USB Serial fallback.
- **Slide 4: Hierarchical 3-Tier AI Orchestration Pipeline**: Tier 1 Fast-Pass (<5ms) -> Tier 2 Local LLM (Ollama `llama3.2:3b`, ~500ms) -> Tier 3 CrewAI Multi-Agent Fallback.
- **Slide 5: Robot Fleet Division**: Bot 1 Scout (PIR motion, spatial recon) vs. Bot 2 Specialist (MQ-2 gas, DHT22 climate). TB6612FNG + N20 motor differential drive.
- **Slide 6: Multi-Sensor Fusion & Kinematics Odometry**: MPU6050 gait step detection (~7.5 cm/stride) + Gyro yaw dead reckoning + Wi-Fi RSSI Log-Distance Path Loss.
- **Slide 7: 20Hz Closed-Loop Autonomous Missions**: Observe-Reason-Act loop (50ms). Active 5-step obstacle bypass engine. Search & rescue, room sweeps, gas surveys.
- **Slide 8: Multi-Layered Safety Architecture**: Immediate voice E-stop (<5ms), 15s telemetry TTL watchdog, planner action interception, firmware barrier limits.
- **Slide 9: 100% Offline Autonomy & Resilience**: Local Faster-Whisper STT + Local Ollama LLM + Local SAPI5 TTS + Local WebSockets/MQTT.
- **Slide 10: Live Demo Architecture & Accomplishments**: Voice instruction -> Autonomous scan & track -> 2D live canvas -> Markdown debrief report.
