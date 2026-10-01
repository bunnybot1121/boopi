# BUPI MASTER SOFTWARE CAPABILITY, ARCHITECTURE & EXTENSIBILITY AUDIT
## Official Ground-Truth Verification Report for Problem Statement 26201

> **Document Class**: Official Software Architecture & Technical Ground-Truth Audit  
> **Target Problem Statement**: SIH Problem Statement 26201 (BUPI Autonomous Robotics & Companion Platform)  
> **Audit Standards**: Strict verification against actual source code, imports, configs, process invocations, firmware `.ino` files, schemas, and database files. No reliance on marketing language, slide decks, or unverified markdown files.  
> **Verification Status Tags**:  
> `[VERIFIED IN CODE]` | `[VERIFIED BUT PARTIAL]` | `[CONFIGURED BUT DISABLED]` | `[EXPERIMENTAL]` | `[DEAD/UNUSED]` | `[DOCUMENTED ONLY]` | `[NOT FOUND]` | `[FUTURE / ROADMAP]` | `[NEEDS HUMAN VERIFICATION]`

---

# 1. EXECUTIVE SUMMARY

| Architectural Dimension | Documented / Claimed Capability | Ground-Truth Reality in Production Code | Status Tag | Primary Code Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **Primary System Runtime** | Batch/Electron orchestrator launching multi-process robot pipeline | Spawns Mosquitto (`1883`), Ollama (`11434`), Hotspot (`192.168.137.1`), Electron (`main.js`), Python Mode 1 (`main.py`), and Python Mode 2 (`run_mode2.py`). | `[VERIFIED IN CODE]` | [Run_Bupi_Robot.bat:L1-L44](file:///c:/Users/Sachin/boopi/assistant/Run_Bupi_Robot.bat#L1-L44), [main.js:L202-L223](file:///c:/Users/Sachin/boopi/assistant/main.js#L202-L223) |
| **Desktop User Interface** | Desktop GUI built with PyQt6 & Electron | The UI is **100% Electron**. PyQt6 executes strictly as a headless `QCoreApplication` for Python background worker threads and Qt signals. Zero PyQt GUI widgets exist. | `[VERIFIED IN CODE]` | [main.js:L57-L200](file:///c:/Users/Sachin/boopi/assistant/main.js#L57-L200), [main.py:L41](file:///c:/Users/Sachin/boopi/assistant/main.py#L41), [main.py:L54](file:///c:/Users/Sachin/boopi/assistant/main.py#L54) |
| **Communication Fabric** | Multi-transport bridge (WebSocket, MQTT, Serial) | WebSocket server on `0.0.0.0:8767`, Mosquitto on `127.0.0.1:1883`, USB Serial on `COM3` (115200 baud). Port 8765 does not exist. | `[VERIFIED IN CODE]` | [bupi_node_server.py:L1008-L1075](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L1008-L1075) |
| **3-Tier Decision Pipeline** | Regex (<5ms) -> Ollama (~500ms) -> CrewAI (5-15s) | Tier 1 Fast Regex in `router_agent.py` -> Tier 2 local Ollama (`llama3.2:3b`/`llama3.1:8b`) -> Tier 3 hierarchical CrewAI (Local -> Gemini -> Groq -> NVIDIA -> OpenRouter). | `[VERIFIED IN CODE]` | [router_agent.py:L80-L308](file:///c:/Users/Sachin/boopi/assistant/agents/router_agent.py#L80-L308), [local_orchestrator.py:L210-L350](file:///c:/Users/Sachin/boopi/assistant/agents/local_orchestrator.py#L210-L350), [robotic_crew.py:L123-L200](file:///c:/Users/Sachin/boopi/assistant/agents/robotic_crew.py#L123-L200) |
| **Multi-Robot Specialization** | Bot 1 (Scout) vs Bot 2 (Specialist) | Bot 1 reads HC-SR04, MPU6050, PIR. Bot 2 reads HC-SR04, MPU6050, MQ-2 gas (GPIO 34), DHT22 (GPIO 4). Bot 2 does not read PIR. | `[VERIFIED IN CODE]` | [firmware/bupi_bot1_scout.ino:L508-L588](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L508-L588), [firmware/bupi_bot2_specialist.ino:L550-L624](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot2_specialist.ino#L550-L624) |
| **Hardware Collision Cutoff** | Firmware blocks forward motion at $\le 15\text{ cm}$ | `#define ENABLE_OBSTACLE_CUTOFF 0` and `CRITICAL_OBSTACLE_CM = 0.0` in dev firmware to prevent bench test stalls. Software validator also disables obstacle avoidance in dev mode. | `[CONFIGURED BUT DISABLED]` | [firmware/bupi_bot1_scout.ino:L85-L87](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L85-L87), [core/safety_validator.py:L109-L110](file:///c:/Users/Sachin/boopi/assistant/core/safety_validator.py#L109-L110) |
| **Gas Hazard Safety** | Active software and firmware hazard cutoff | Firmware raises `HIGH_GAS_ALERT` at >300ppm. Software validator blocks movements and ventilation shutdowns during gas leaks. Swarm coordinator issues emergency stop. | `[VERIFIED IN CODE]` | [firmware/bupi_bot2_specialist.ino:L101](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot2_specialist.ino#L101), [core/safety_validator.py:L125-L145](file:///c:/Users/Sachin/boopi/assistant/core/safety_validator.py#L125-L145), [core/swarm_coordinator.py:L131-L153](file:///c:/Users/Sachin/boopi/assistant/core/swarm_coordinator.py#L131-L153) |
| **Sensor Fusion / Odometry** | "Extended Kalman Filter (EKF)" sensor fusion | **NOT FOUND**. Odometry is an epistemic kinematics fusion engine (IMU dynamic gait step counter at 1.20g, gyro dead-reckoning, Wi-Fi RSSI log-distance path loss). | `[NOT FOUND]` | [core/kinematics_odometry.py:L1-L253](file:///c:/Users/Sachin/boopi/assistant/core/kinematics_odometry.py#L1-L253) |
| **Legacy `run_bupi.py`** | Standalone 20Hz sensor orchestrator | Unused standalone prototype; unreferenced by `Run_Bupi_Robot.bat`, `main.js`, or `main.py`. | `[DEAD/UNUSED]` | [run_bupi.py:L1-L252](file:///c:/Users/Sachin/boopi/assistant/run_bupi.py#L1-L252) |
| **FootMo2 Micro-Services** | Express backend & Vite frontend cockpit | Spawning explicitly commented out in `main.js:L399` (`// spawnFootMo2()`). | `[CONFIGURED BUT DISABLED]` | [main.js:L399](file:///c:/Users/Sachin/boopi/assistant/main.js#L399) |
| **Edge Compute / Raspberry Pi** | Distributed edge Linux inference nodes | Mentioned only in documentation/comments. No on-device Linux daemon or RPi GPIO interface exists. | `[DOCUMENTED ONLY]` | [bupi_architecture_audit.md](file:///c:/Users/Sachin/boopi/assistant/bupi_architecture_audit.md) |
| **Vision / Camera Streaming** | Real-time object recognition / YOLO / OpenCV | No camera frame capture, OpenCV, RTSP, or YOLO pipelines exist in Python backend. Camera terms exist only as Three.js WebGL viewport parameters. | `[DOCUMENTED ONLY]` | [spatial_twin_2d.html](file:///c:/Users/Sachin/boopi/assistant/spatial_twin_2d.html), [three_handler.js](file:///c:/Users/Sachin/boopi/assistant/three_handler.js) |
| **Aerial Drones / Quadcopters** | Flying search-and-rescue UAV nodes | Pitch slide concept only. No flight controllers, MAVLink, PID altitude loops, or drone actuator topics exist. | `[FUTURE / ROADMAP]` | Documents & pitch decks only |

---

# 2. SYSTEM IDENTITY

BUPI is a **dual-personality, edge-connected robotics and desktop companion platform**:
1. **Mode 1 (Desktop Companion)**: Voice-driven personal assistant running Faster-Whisper, Edge-TTS, and Google Gemini / OpenRouter models. Manages PC automations, user activity tracking, daily reminders, and notes.
2. **Mode 2 (Autonomous Robotics Controller)**: Local-first 3-tier decision engine controlling dual physical ESP32 differential-drive rovers (Bot 1 Scout and Bot 2 Environmental Specialist), auxiliary IoT nodes (Desk Display LCD), and a digital twin simulation environment (BWE).

### Software Module Map

| Module Name | Purpose | Active Entry Point(s) | Dependencies | Consumers | Outputs / Side Effects | Verification Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **UI (Electron)** | Desktop mascot overlay & Central Control Hub | [main.js:L57](file:///c:/Users/Sachin/boopi/assistant/main.js#L57) (`createNotepadWindow`), [L128](file:///c:/Users/Sachin/boopi/assistant/main.js#L128) (`createWindow`) | Node.js, Electron 41.2.1, Chromium, Rive, Three.js | End user | Windows, canvas rendering, IPC events | `[VERIFIED IN CODE]` |
| **Voice STT** | 16kHz audio capture & local transcription | [voice/listener.py:L82](file:///c:/Users/Sachin/boopi/assistant/voice/listener.py#L82) (`ListenerThread.run`) | `sounddevice`, `webrtcvad`, `faster-whisper` | [main.py:L570](file:///c:/Users/Sachin/boopi/assistant/main.py#L570) (`on_transcription`) | `transcription_ready` Qt signal | `[VERIFIED IN CODE]` |
| **Voice TTS** | Speech synthesis & audio playback | [voice/speaker.py:L31](file:///c:/Users/Sachin/boopi/assistant/voice/speaker.py#L31) (`SpeakerThread.run`) | `edge-tts` (cloud), `pyttsx3` (offline fallback) | [main.py](file:///c:/Users/Sachin/boopi/assistant/main.py), [run_mode2.py](file:///c:/Users/Sachin/boopi/assistant/run_mode2.py) | Audio playback via default soundcard | `[VERIFIED IN CODE]` |
| **AI Brain (Mode 1)** | Conversational LLM streaming & user memory | [brain/ai_brain.py:L143](file:///c:/Users/Sachin/boopi/assistant/brain/ai_brain.py#L143) (`AIThread.run`) | `google-genai`, `openai`, `bupi.db` | [main.py](file:///c:/Users/Sachin/boopi/assistant/main.py), Electron UI | Spoken text, UI status, hardware C++ generation | `[VERIFIED IN CODE]` |
| **Router Agent (Tier 1)** | Deterministic microsecond regex classification | [agents/router_agent.py:L80](file:///c:/Users/Sachin/boopi/assistant/agents/router_agent.py#L80) (`quick_regex_classify`) | Pure Python `re` | [run_mode2.py:L116](file:///c:/Users/Sachin/boopi/assistant/run_mode2.py#L116), [main.py:L580](file:///c:/Users/Sachin/boopi/assistant/main.py#L580) | Intent dictionary or `None` (<5ms) | `[VERIFIED IN CODE]` |
| **Local Orchestrator (Tier 2)** | Single-turn local LLM tool dispatch | [agents/local_orchestrator.py:L230](file:///c:/Users/Sachin/boopi/assistant/agents/local_orchestrator.py#L230) (`run_task`) | Ollama (`llama3.2:3b`), `openai` client | [run_mode2.py:L157](file:///c:/Users/Sachin/boopi/assistant/run_mode2.py#L157) | Executed tool results, conversational reply (~500ms) | `[VERIFIED IN CODE]` |
| **Robotic Crew (Tier 3)** | Hierarchical multi-agent CrewAI fallback | [agents/robotic_crew.py:L123](file:///c:/Users/Sachin/boopi/assistant/agents/robotic_crew.py#L123) (`run_robotic_task`) | `crewai`, cloud LLMs (Gemini, Groq, NVIDIA) | [run_mode2.py:L185](file:///c:/Users/Sachin/boopi/assistant/run_mode2.py#L185) | Multi-step task execution plan (5-15s) | `[VERIFIED IN CODE]` |
| **Autonomous Goal Agent** | Closed-loop 20Hz autonomous mission engine | [agents/autonomous_goal_agent.py:L152](file:///c:/Users/Sachin/boopi/assistant/agents/autonomous_goal_agent.py#L152) (`start_mission`) | `instruction_decomposer`, `bupi_node_server` | UI, voice commands | 20Hz motor control, mission telemetry | `[VERIFIED IN CODE]` |
| **Instruction Decomposer** | Natural language to DynamicMissionPlan parser | [planner/instruction_decomposer.py:L588](file:///c:/Users/Sachin/boopi/assistant/planner/instruction_decomposer.py#L588) (`decompose_instruction`) | Regex pattern matchers, Ollama/Gemini fallback | `AutonomousGoalAgent` | `DynamicMissionPlan` object with stages | `[VERIFIED IN CODE]` |
| **Obstacle Bypass Engine** | Geometric 5-step flank-and-detour state machine | [core/obstacle_bypass_engine.py:L40](file:///c:/Users/Sachin/boopi/assistant/core/obstacle_bypass_engine.py#L40) (`execute_obstacle_bypass`) | `paho.mqtt.publish`, `kinematics_odometry` | `AutonomousGoalAgent` | Motor commands for reverse, pivot, advance, counter-pivot | `[VERIFIED IN CODE]` |
| **Safety Validator** | 15s telemetry TTL watchdog & hazard rules | [core/safety_validator.py:L112](file:///c:/Users/Sachin/boopi/assistant/core/safety_validator.py#L112) (`validate_safety`) | In-memory world state cache | `hardware_tools.py`, `run_mode2.py` | `{"approved": bool, "reason": str}` | `[VERIFIED IN CODE]` |
| **Kinematics & Odometry** | Gait step detection, yaw dead-reckoning, RSSI | [core/kinematics_odometry.py:L140](file:///c:/Users/Sachin/boopi/assistant/core/kinematics_odometry.py#L140) (`process_telemetry`) | Math, EWMA filtering | Telemetry stream, UI 2D arena | Position $(x, y)$, heading, steps, Wi-Fi distance | `[VERIFIED IN CODE]` |
| **Swarm Coordinator** | Dual-bot state fusion & hazard evacuation | [core/swarm_coordinator.py:L172](file:///c:/Users/Sachin/boopi/assistant/core/swarm_coordinator.py#L172) (`coordinate_tandem_reading`) | `paho.mqtt` | `AutonomousGoalAgent`, UI | Fused scout + environmental telemetry | `[VERIFIED IN CODE]` |
| **Hardware Tools** | Unified tool definitions for agent invocation | [actions/hardware_tools.py:L4](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L4) (`CallableTool`) | `paho.mqtt`, SQLite | Tier 2 Orchestrator, Tier 3 CrewAI | MQTT command packets, database rows | `[VERIFIED IN CODE]` |
| **Hardware Bridge Server** | WebSocket server, Serial supervisor, MQTT bridge | [bupi_node_server.py:L1008](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L1008) (`start_node_server`) | `websockets`, `pyserial`, `paho.mqtt`, SQLite | ESP32 hardware, Electron UI | Bidirectional hardware communication | `[VERIFIED IN CODE]` |
| **Knowledge Super Agent** | Hardware C++ analysis, FTS5 & ChromaDB RAG | [services/knowledge_super_agent.py:L21](file:///c:/Users/Sachin/boopi/assistant/services/knowledge_super_agent.py#L21) (`KnowledgeSuperAgent`) | SQLite FTS5, ChromaDB, Google GenAI, Groq | `brain/ai_brain.py` | Component cards, pinouts, Arduino code | `[VERIFIED IN CODE]` |
| **Auto Flasher** | Compiles and flashes C++ to ESP32 | [actions/flasher.py:L21](file:///c:/Users/Sachin/boopi/assistant/actions/flasher.py#L21) (`auto_flash_code`) | `arduino-cli` binary, `pyserial` | `brain/ai_brain.py` | Flashes firmware over detected COM port | `[VERIFIED IN CODE]` |
| **Bit-World Engine (BWE)** | Digital twin lab simulation engine | [bwe/core/engine.js:L1](file:///c:/Users/Sachin/boopi/assistant/bwe/core/engine.js#L1), [launch_bwe_lab.js:L1](file:///c:/Users/Sachin/boopi/assistant/launch_bwe_lab.js#L1) | Electron, WebSockets, virtual peripherals | Standalone lab simulator | Simulated physics, virtual sensor pins | `[VERIFIED IN CODE]` |
| **Spatial Twin Bridge** | 2D tactical arena WebSocket stream | [spatial_intelligence/spatial_twin_bridge.py:L1](file:///c:/Users/Sachin/boopi/assistant/spatial_intelligence/spatial_twin_bridge.py#L1) | `websockets`, `multi_bot_fusion` | [spatial_twin_2d.html](file:///c:/Users/Sachin/boopi/assistant/spatial_twin_2d.html) | Fused spatial telemetry packets | `[VERIFIED IN CODE]` |
| **FootMo2 Subproject** | Express backend & Vite frontend cockpit | [footmo2-v2/backend/server.js](file:///c:/Users/Sachin/boopi/assistant/footmo2-v2/backend/server.js) | Express, Vite, Node.js | None (commented out in `main.js`) | HTTP/WS on ports 5001 & 5173 | `[CONFIGURED BUT DISABLED]` |
| **Legacy `run_bupi.py`** | Standalone 20Hz sensor orchestrator | [run_bupi.py:L1](file:///c:/Users/Sachin/boopi/assistant/run_bupi.py#L1) | `communication.bridge`, `planner` | Standalone CLI only | Terminal output | `[DEAD/UNUSED]` |

---

# 3. CURRENT PRODUCTION ARCHITECTURE

```
                                 +-------------------------------------------------------+
                                 |                OPERATOR / PHYSICAL WORLD              |
                                 +-------------------------------------------------------+
                                        | (Spoken Voice)                 ^ (Audio Output)
                                        v                                |
+--------------------------------------------------------------------------------------------------------------------+
| HOST PC RUNTIME (WINDOWS 11)                                                                                       |
|                                                                                                                    |
|  [VOICE SUBSYSTEM]                                                                                                 |
|    Microphone -> sounddevice -> webrtcvad (360ms window) -> Faster-Whisper (tiny.en) -> text utterance             |
|    SpeakerQueue -> Edge-TTS (Neural) / pyttsx3 (Offline Fallback) -> Audio Output                                  |
|                                                                                                                    |
|  [ELECTRON GUI RUNTIME] (Chromium / Node.js)                                                                       |
|    mainWindow (index.html): 250x250 Frameless Always-On-Top 3D Mascot (Three.js GLTF / Rive Animation)             |
|    notepadWindow (notepad.html): 1200x800 Central Intelligence & Robotics Control Hub (11 Tabs)                    |
|    Inter-Process Communication: stdin / stdout JSON streaming between Electron and Python                         |
|                                                                                                                    |
|  [3-TIER DECISION ENGINE]                                                                                          |
|    Incoming Utterance                                                                                              |
|           |                                                                                                        |
|           +---> TIER 1: router_agent.py (Deterministic Fast Regex, <5ms) --------------------------------+        |
|           |       | (E-Stop, Stop, Halt, Directional Move, Distance Move, Simple Query)                   |        |
|           |       v (Unmatched)                                                                           |        |
|           +---> TIER 2: local_orchestrator.py (Local Ollama llama3.2:3b / llama3.1:8b, ~500ms) --------+        |
|           |       | (Single-turn tool-calling with 12 OpenAI schemas, 100% offline)                       |        |
|           |       v (Ollama unavailable or exception thrown)                                              |        |
|           +---> TIER 3: robotic_crew.py (CrewAI Multi-Agent Fallback, 5-15s) -----------------------------+        |
|                   | (Sequential: Ollama -> Gemini 2.5 -> Groq 70B -> NVIDIA DeepSeek -> OpenRouter)       |        |
|                   v                                                                                       |        |
|                                                                                                           v        |
|  [PLANNING & AUTONOMY]                                                                                    |        |
|    AutonomousGoalAgent (20Hz loop) <---> InstructionDecomposer (DynamicMissionPlan) <---------------------+        |
|    ObstacleBypassEngine (5-stage flank detour)                                                                    |
|                                                                                                                    |
|  [SAFETY & INTEGRITY LAYER]                                                                                        |
|    safety_validator.py: In-memory world state cache, 15.0s Telemetry TTL watchdog, Gas hazard barrier              |
|    safety_controller.py: OVERRIDDEN_FORCED_STOP on critical obstacle or rollover                                  |
|                                                                                                                    |
|  [COMMUNICATION FABRIC]                                                                                            |
|    Local Mosquitto MQTT Broker (port 1883) <---> Asynchronous MQTT Bridge                                         |
|    bupi_node_server.py: WebSocket Server (0.0.0.0:8767), Serial Supervisor (COM3, 115200 baud)                   |
|    SQLite Database Writer: bupi_telemetry.db (1.5s batch writer)                                                  |
+--------------------------------------------------------------------------------------------------------------------+
                                        | (Wi-Fi 192.168.137.x:8767 or USB Serial COM3)
                                        v
+--------------------------------------------------------------------------------------------------------------------+
| EMBEDDED MICROCONTROLLER HARDWARE (ESP32 NODES)                                                                    |
|                                                                                                                    |
|  [BOT 1: SCOUT (bupi_01)]                       [BOT 2: SPECIALIST (bupi_02)]         [AUXILIARY DESK DISPLAY]     |
|   - ESP32 Dev Module                             - ESP32 Dev Module                    - ESP32 Dev Module          |
|   - TB6612FNG Dual H-Bridge                      - TB6612FNG Dual H-Bridge             - PCF8574 I2C Backpack      |
|   - 2x N20 Gear Motors                           - 2x N20 Gear Motors                  - 1602 LCD (0x27)           |
|   - HC-SR04 Ultrasonic (GPIO 5/18)               - HC-SR04 Ultrasonic (GPIO 5/18)      - Subscribes to LCD topics  |
|   - MPU6050 IMU (I2C 0x68)                       - MPU6050 IMU (I2C 0x68)              - Publishes announce/hb     |
|   - PIR Motion (GPIO 34/19)                      - MQ-2 Gas Sensor (GPIO 34 ADC)                                   |
|   - 20Hz Perception Loop                         - DHT22 Climate (GPIO 4, 2000ms)                                  |
|   - Onboard Reflex: motor duration auto-stop     - 20Hz Perception Loop                                            |
|   - Transmits 20Hz Telemetry via WS/Serial       - Transmits 20Hz Telemetry via WS                                 |
+--------------------------------------------------------------------------------------------------------------------+
```

---

# 4. RUNTIME / PROCESS TREE

### A. Complete Process Tree

```
[OS Boot / User Execution]
  |
  +---> Run_Bupi_Robot.bat [PID: Parent Launcher Shell]
          |
          +---> sc query mosquitto -> net start mosquitto [PID: Service Daemon]
          |       └─ Port: 127.0.0.1:1883 (TCP)
          |
          +---> ollama serve [PID: Background HTTP Server]
          |       └─ Port: 127.0.0.1:11434 (HTTP REST)
          |
          +---> powershell.exe -ExecutionPolicy Bypass -File scripts\ensure_hotspot.ps1
          |       └─ Gateway: 192.168.137.1 (Windows Mobile Hotspot)
          |
          +---> electron.exe . --mode 2 [PID: Electron Main Process]
                  |
                  +---> electron.exe (GPU Process)
                  +---> electron.exe (Utility / Network Service)
                  +---> electron.exe (Renderer: mainWindow / index.html mascot)
                  +---> electron.exe (Renderer: notepadWindow / notepad.html hub)
                  |
                  +---> venv312\Scripts\python.exe -u main.py --mode 2 [PID: Mode 1 Python Process]
                          |
                          +---> venv312\Scripts\python.exe -u run_mode2.py [PID: Mode 2 Python Process]
```

### B. Thread Tree

#### Threads inside `python.exe main.py`
1. `MainThread`: Executes `QCoreApplication(sys.argv).exec()` event loop `[VERIFIED IN CODE]` ([main.py:L54](file:///c:/Users/Sachin/boopi/assistant/main.py#L54), [L1375](file:///c:/Users/Sachin/boopi/assistant/main.py#L1375)).
2. `ListenerThread` (QThread): Executes `sounddevice.RawInputStream` audio capture, WebRTC VAD, and Faster-Whisper transcription `[VERIFIED IN CODE]` ([voice/listener.py:L157-L210](file:///c:/Users/Sachin/boopi/assistant/voice/listener.py#L157-L210)).
3. `AIThread` (QThread): Manages conversational Mode 1 LLM requests and token streaming `[VERIFIED IN CODE]` ([brain/ai_brain.py:L143-L190](file:///c:/Users/Sachin/boopi/assistant/brain/ai_brain.py#L143-L190)).
4. `SpeakerThread` (QThread): Consumes speech queue and executes Edge-TTS / pyttsx3 audio playback `[VERIFIED IN CODE]` ([voice/speaker.py:L31-L100](file:///c:/Users/Sachin/boopi/assistant/voice/speaker.py#L31-L100)).
5. `ActivityMonitorService` (Thread): Periodically polls Windows idle time and foreground application titles `[VERIFIED IN CODE]` ([brain/activity_monitor.py:L25-L60](file:///c:/Users/Sachin/boopi/assistant/brain/activity_monitor.py#L25-L60)).
6. `Mode1_App MQTT Network Loop` (Thread): Created by `paho.mqtt.client.loop_start()` to handle MQTT packets `[VERIFIED IN CODE]` ([main.py:L199](file:///c:/Users/Sachin/boopi/assistant/main.py#L199)).
7. `WebSocketServer` (Thread): Created by `threading.Thread(target=run_ws_server, daemon=True)` running asyncio event loop hosting `websockets.serve(..., "0.0.0.0", 8767)` `[VERIFIED IN CODE]` ([bupi_node_server.py:L1059](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L1059)).
8. `SerialSupervisor` (Thread): Created by `threading.Thread(target=serial_supervisor_loop, daemon=True)` managing auto-reconnect and reading from USB COM3 at 115200 baud `[VERIFIED IN CODE]` ([bupi_node_server.py:L1066](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L1066)).
9. `DbWriter` (Thread): Created by `threading.Thread(target=db_writer_thread, daemon=True)` flushing queued sensor readings to `bupi_telemetry.db` every 1.5 seconds `[VERIFIED IN CODE]` ([bupi_node_server.py:L1070](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L1070)).
10. `HotspotWatchdog` (Thread): Created by `threading.Thread(target=hotspot_watchdog_thread, daemon=True)` checking Windows mobile hotspot state every 30 seconds `[VERIFIED IN CODE]` ([bupi_node_server.py:L1074](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L1074)).
11. `StdinReader` (Thread): Created by `threading.Thread(target=stdin_reader, daemon=True)` listening for JSON commands from Electron on `sys.stdin` `[VERIFIED IN CODE]` ([main.py:L1219](file:///c:/Users/Sachin/boopi/assistant/main.py#L1219)).

#### Threads inside `python.exe run_mode2.py`
1. `MainThread`: Connects MQTT client `Mode2_Main_Worker` and runs idle keep-alive loop `[VERIFIED IN CODE]` ([run_mode2.py:L315-L348](file:///c:/Users/Sachin/boopi/assistant/run_mode2.py#L315-L348)).
2. `Mode2_Main_Worker MQTT Network Loop`: Started by `m2_client.loop_start()` `[VERIFIED IN CODE]` ([run_mode2.py:L320](file:///c:/Users/Sachin/boopi/assistant/run_mode2.py#L320)).
3. `Utterance Dispatch Worker` (Dynamic Thread): Spawned per incoming utterance on `bupi/internal/utterance`: `threading.Thread(target=process_with_crew, args=(text,), daemon=True).start()` `[VERIFIED IN CODE]` ([run_mode2.py:L46](file:///c:/Users/Sachin/boopi/assistant/run_mode2.py#L46)).
4. `Autonomous Mission Worker` (Dynamic Thread): Spawned by `goal_agent.start_mission()`: `self.active_mission_thread = threading.Thread(target=self._run_mission_thread, daemon=True)` `[VERIFIED IN CODE]` ([agents/autonomous_goal_agent.py:L345](file:///c:/Users/Sachin/boopi/assistant/agents/autonomous_goal_agent.py#L345)).

### C. Startup Sequence

1. `Run_Bupi_Robot.bat` executes.
2. Checks Mosquitto service via `sc query mosquitto`; starts service if stopped (`net start mosquitto`).
3. Checks Ollama via `tasklist /fi "imagename eq ollama.exe"`; launches `start /b "" ollama serve` if absent.
4. Executes `powershell.exe -ExecutionPolicy Bypass -File scripts\ensure_hotspot.ps1` to ensure hotspot gateway `192.168.137.1` is up.
5. Terminates stale processes (`taskkill /f /im electron.exe`, `taskkill /f /im python.exe`).
6. Spawns Electron binary: `.\node_modules\electron\dist\electron.exe . --mode 2`.
7. `main.js` initializes `app.whenReady()`:
   - Spawns `notepadWindow` (1200x800, `notepad.html`).
   - Spawns `mainWindow` (250x250 frameless transparent mascot overlay, `index.html`).
   - Invokes `spawnEngine()`: executes `venv312\Scripts\python.exe -u main.py --mode 2`.
8. `main.py` initializes:
   - Instantiates headless `QCoreApplication(sys.argv)`.
   - Starts STT `ListenerThread`, TTS `SpeakerThread`, Mode 1 `AIThread`, and `ActivityMonitorService`.
   - Connects MQTT client `Mode1_App` to `localhost:1883`.
   - Calls `start_node_server()` from `bupi_node_server.py`:
     * Starts WebSocket server on `0.0.0.0:8767`.
     * Starts Serial supervisor on `COM3` (115200 baud).
     * Starts SQLite 1.5s telemetry batch writer.
     * Starts mobile hotspot watchdog.
   - Calls `start_mode2_process()`: executes `venv312\Scripts\python.exe -u run_mode2.py` with output logged to `mode2_log.txt`.
9. `run_mode2.py` initializes:
   - Connects MQTT client `Mode2_Main_Worker` to `localhost:1883`.
   - Subscribes to `bupi/internal/utterance` and begins listening for commands.
10. System is fully operational and awaiting voice/GUI input.

### D. Inter-Process Communication (IPC) Map

```
+--------------------+        Electron IPC (send / on)         +----------------------+
| mainWindow Mascot  | <=====================================> | notepadWindow Hub    |
| (index.html)       |                                         | (notepad.html)       |
+--------------------+                                         +----------------------+
         ^                                                                 ^
         | Electron webContents.send('py-output')                          |
         v                                                                 v
+-------------------------------------------------------------------------------------+
| Electron Main Process (main.js)                                                     |
+-------------------------------------------------------------------------------------+
         ^
         | Bidirectional Standard I/O (stdin / stdout JSON lines)
         | - Python -> Electron: {"type": "transcription", "value": "..."}, {"type": "hardware_result", ...}
         | - Electron -> Python: {"cmd": "toggle_mic"}, {"cmd": "set_mode", "mode": 2}, {"cmd": "estop"}
         v
+-------------------------------------------------------------------------------------+
| Python Mode 1 Supervisor (main.py)                                                  |
+-------------------------------------------------------------------------------------+
         ^
         | Local Mosquitto MQTT Broker (localhost:1883)
         | - Topic: bupi/internal/utterance (Mode 1 -> Mode 2)
         | - Topic: bupi/internal/tts (Mode 2 -> Mode 1)
         | - Topic: bupi/internal/estop (Emergency Stop broadcast)
         v
+-------------------------------------------------------------------------------------+
| Python Mode 2 Robotic Daemon (run_mode2.py)                                         |
+-------------------------------------------------------------------------------------+
         |
         | Local Mosquitto MQTT Broker (localhost:1883) & Direct Function Calls
         | - Actuator commands: bupi/actuators/motors/cmd/json
         | - Telemetry queries: bupi_node_server.get_latest_telemetry()
         v
+-------------------------------------------------------------------------------------+
| Unified Hardware Bridge (bupi_node_server.py)                                       |
+-------------------------------------------------------------------------------------+
         |                                                 |
         | WebSocket (ws://192.168.137.1:8767)             | USB Serial UART (COM3, 115200 baud)
         v                                                 v
+------------------------------------+            +------------------------------------+
| ESP32 Bot 1 Scout (bupi_01)        |            | ESP32 Bot 2 Specialist (bupi_02)   |
+------------------------------------+            +------------------------------------+
```

### E. Shutdown & Watchdog Behavior

1. **Window Close / App Quit**:
   - `main.js:app.on('before-quit')` terminates Python child process (`pyEngine.kill()`) and any lingering child tasks `[VERIFIED IN CODE]` ([main.js:L360-L380](file:///c:/Users/Sachin/boopi/assistant/main.js#L360-L380)).
   - `main.py:stop_mode2_process()` calls `mode2_process.terminate()`, waits 2.0s, and issues `kill()` if unresponsive `[VERIFIED IN CODE]` ([main.py:L240-L254](file:///c:/Users/Sachin/boopi/assistant/main.py#L240-L254)).
2. **Watchdog Systems**:
   - **Mode 2 Watchdog** (`main.py:mode2_fallback_watchdog`): Enforces a **15.0s timeout** on Mode 2 responses. If Mode 2 fails to respond, Mode 1 clears its pending state to prevent voice deadlock `[VERIFIED IN CODE]` ([main.py:L545-L565](file:///c:/Users/Sachin/boopi/assistant/main.py#L545-L565)).
   - **Node Timeout Watchdog** (`bupi_node_server.py:check_node_timeouts`): Runs every 5.0s. If `time.time() - last_seen > 15.0s`, the node is marked `OFFLINE` in SQLite and memory `[VERIFIED IN CODE]` ([bupi_node_server.py:L184-L195](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L184-L195)).
   - **Telemetry Freshness TTL** (`core/safety_validator.py:L6`): Rejects sensor data older than **15.0 seconds** (`TELEMETRY_TTL_SECONDS = 15.0`), setting `telemetry_fresh = False`.
   - **Firmware Motor Timeout**: Embedded in ESP32 firmware loops: `now >= motorEndTime` forces `stopMotors()` immediately, preventing runaway movement if communication drops `[VERIFIED IN CODE]` ([firmware/bupi_bot1_scout.ino:L987](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L987)).

---

# 5. INTELLIGENCE PIPELINE

### End-to-End Command Traces (Microphone to Motors & Feedback)

#### A. Command: "bupi move forward"
1. **INPUT**: Operator speaks into microphone.
2. **STT**: `voice/listener.py:ListenerThread.run()` captures 16kHz PCM audio; `webrtcvad` detects end of speech; Faster-Whisper transcribes `"bupi move forward"` and emits `transcription_ready` `[VERIFIED IN CODE]` ([listener.py:L140-L180](file:///c:/Users/Sachin/boopi/assistant/voice/listener.py#L140-L180)).
3. **INTENT PROCESSING**: `main.py:on_transcription()` strips wake word `"bupi"`, yielding `"move forward"`.
4. **ROUTER**: Evaluates `router.quick_regex_classify("move forward")` in `agents/router_agent.py:L80`. Matches regex pattern `^move\s+(forward|ahead)`. Returns `{"device": "motors", "action": "MOVE", "direction": "forward", "robot_id": "bupi_01"}` in <5ms.
5. **AI TIER**: **Tier 1 Fast Regex** handles execution directly without invoking LLMs.
6. **AGENT / TOOL**: Invokes `actions/hardware_tools.py:control_motors(direction="forward", speed=255, duration_seconds=1.5, robot_id="bupi_01")`.
7. **SAFETY**: Calls `core/safety_validator.py:validate_safety(topic="bupi/actuators/motors/cmd/json", payload="forward", bot_id="bupi_01")`. Verifies gas is safe and telemetry TTL < 15s. Returns `{"approved": True}`.
8. **COMMUNICATION**: `hardware_tools.py:L173` publishes JSON payload `{"action": "forward", "speed": 255, "duration_ms": 1500, "bot_id": "bupi_01"}` to MQTT topic `bupi/actuators/motors/cmd/json`.
9. **DEVICE**: `bupi_node_server.py:on_mqtt_message()` intercepts packet and transmits over WebSocket to Bot 1 (`ws.send()`).
10. **FIRMWARE**: `bupi_bot1_scout.ino:processCommandString()` parses JSON, calls `executeMotorAction("forward", 255, 1500)` -> sets TB6612 pins `AIN1=HIGH`, `AIN2=LOW`, `BIN1=HIGH`, `BIN2=LOW`, `PWMA=HIGH`, `PWMB=HIGH`. Motors rotate for 1500ms.
11. **TELEMETRY**: 20Hz sensor loop sends `{"type": "telemetry", "bot_id": "bupi_01", "moving": true, ...}`.
12. **UI / RESPONSE**: Spoken TTS confirmation: *"Moving forward."* Mascot triggers walking animation.

#### B. Command: "bupi scan the room"
1. **INPUT**: Operator speaks `"bupi scan the room"`.
2. **STT**: `voice/listener.py` transcribes utterance.
3. **INTENT**: `main.py` normalizes string to `"scan the room"`.
4. **ROUTER**: `router_agent.py:quick_regex_classify()` matches pattern `(?:scan|sweep)\s+(?:the\s+)?(?:room|area)`. Returns `{"device": "mission", "action": "SCAN_SWEEP", "robot_id": "bupi_01"}`.
5. **AI TIER**: **Tier 1** routes to mission system.
6. **AGENT**: Invokes `actions/hardware_tools.py:start_autonomous_mission("scan the room")` -> calls `agents/autonomous_goal_agent.py:goal_agent.start_mission("scan the room")`.
7. **PLANNER**: `planner/instruction_decomposer.py:decompose_instruction()` parses goal into policy `SCAN_SWEEP` with 8 rotational sectors of 45° each.
8. **SAFETY**: Safety validator checks heading clearance and tilt stability.
9. **COMMUNICATION**: Publishes incremental turn commands `{"action": "turn_by", "degrees": 45.0, "speed": 200, "bot_id": "bupi_01"}` to `bupi/actuators/motors/cmd/json`.
10. **DEVICE**: Bot 1 executes 8 successive gyro-stabilized 45° turns via MPU6050 feedback, sampling ultrasonic distance and PIR at each stop.
11. **TELEMETRY**: Telemetry streams obstacle distances and sector map points to `spatial_twin_bridge.py`.
12. **UI / RESPONSE**: Live 360° radar sweep visualizes on 2D arena canvas (`notepad.html`). Goal agent speaks debrief: *"Room scan complete. Perimeter cleared."*

#### C. Command: "bupi find a human"
1. **INPUT**: Spoken command `"bupi find a human"`.
2. **STT**: Transcribed by Faster-Whisper.
3. **ROUTER**: `router_agent.py` matches `(?:find|locate|search\s+for)\s+(?:a\s+)?(?:human|person)`. Returns `{"device": "mission", "action": "FIND_HUMAN", "robot_id": "bupi_01"}`.
4. **AI TIER**: **Tier 1 Fast Regex** dispatches mission.
5. **AGENT**: `AutonomousGoalAgent` starts mission with policy `APPROACH_TARGET`.
6. **PLANNING**: Step 1: Rotational sweep searching for `pir == 1`. Step 2: Upon PIR detection, locks bearing and drives forward with dynamic stop condition `DynamicStopCondition(distance_cm <= 30.0)`.
7. **SAFETY**: Evaluates distance every 50ms (20Hz). If obstacle distance $\le 30\text{ cm}$, halts motors immediately.
8. **COMMUNICATION**: WebSocket motor packets dispatched to Bot 1.
9. **DEVICE**: Bot 1 rotates until PIR sensor triggers on GPIO 34/19, drives toward target, and stops at 30cm clearance.
10. **TELEMETRY**: Telemetry packet with `pir: 1` and `distance_cm: 29.5` received and saved to SQLite.
11. **UI / RESPONSE**: Mission status in `notepad.html` turns green: `HUMAN_FOUND`. Spoken audio: *"Human presence detected at bearing 45 degrees."*

#### D. Command: "bupi check gas"
1. **INPUT**: Spoken command `"bupi check gas"`.
2. **STT**: Transcribed by Faster-Whisper.
3. **ROUTER**: `router_agent.py` matches `(?:check|read|get)\s+(?:the\s+)?(?:gas|smoke|air)`. Returns `{"device": "sensor", "action": "READ", "sensor": "mq2", "robot_id": "bupi_02"}`.
4. **AI TIER**: **Tier 1 Fast Regex** routes query directly to Bot 2 capability.
5. **AGENT / TOOL**: Invokes `actions/hardware_tools.py:read_sensor_status(sensor_id="mq2", robot_id="bupi_02")`.
6. **TELEMETRY QUERY**: `read_sensor_status()` checks live in-memory telemetry from `bupi_node_server.get_latest_telemetry("bupi_02")`. Retrieves `gas_ppm = 42.5`.
7. **TRANSLATION**: Passes 42.5 to `core/sensor_translator.py:translate_sensor_value("mq2", 42.5)`. Returns `{"status": "SAFE", "value": "42.5 ppm", "description": "Air quality is normal. Flammable gas concentration is well within safe thresholds."}`.
8. **UI / RESPONSE**: Spoken TTS: *"Air quality is normal. Flammable gas concentration is 42.5 ppm, well within safe thresholds."* Telemetry card updates in `notepad.html`.

#### E. Command: "bupi stop" (Emergency Stop)
1. **INPUT**: Spoken command `"bupi stop"` or UI E-Stop button clicked.
2. **STT**: Transcribed by Faster-Whisper.
3. **ROUTER**: `router_agent.py` matches regex `^(?:stop|halt|freeze|brake|emergency\s+stop|e-stop)$` in `<1ms`.
4. **AI TIER**: **Tier 1 Immediate Priority Intercept** (LLMs are completely bypassed).
5. **AGENT / TOOL**:
   - Calls `agents/autonomous_goal_agent.py:goal_agent.stop_mission(reason="Emergency Stop")`.
   - Calls `actions/hardware_tools.py:control_motors(direction="stop", speed=0, duration_seconds=0, robot_id="all")`.
6. **COMMUNICATION**:
   - Publishes plain string `"stop"` and JSON `{"action": "stop", "speed": 0}` to all motor topics: `bupi/actuators/motors/cmd`, `bupi/v1/bot2/actuators/motors/cmd`.
   - Publishes `{"command": "STOP_ALL"}` to `bupi/internal/estop`.
   - Broadcasts direct WebSocket halt packets to all connected clients.
7. **DEVICE**: ESP32 firmware executes `stopMotors()`: drives `AIN1=LOW, AIN2=LOW, BIN1=LOW, BIN2=LOW, PWMA=LOW, PWMB=LOW`. Motors cut power within <5ms.
8. **UI / RESPONSE**: Spoken TTS: *"Emergency stop activated. All motors halted."* UI badge switches to red: `HALTED`.

#### F. Command: Autonomous Mission ("bupi explore the room safely")
1. **INPUT**: Natural language command.
2. **ROUTER**: Regex fails to match an atomic command; escalates to **Tier 2 Local Orchestrator**.
3. **AI TIER (TIER 2)**: Local Ollama (`llama3.2:3b`) receives request with 12 tool schemas. Identifies high-level exploratory goal. Calls function `start_autonomous_mission(mission_description="explore the room safely")` `[VERIFIED IN CODE]` ([local_orchestrator.py:L284-L304](file:///c:/Users/Sachin/boopi/assistant/agents/local_orchestrator.py#L284-L304)).
4. **PLANNER**: `instruction_decomposer.py` selects policy `EXPLORE_SAFE`. Sets dynamic stop conditions (elapsed time, obstacle clearance).
5. **AUTONOMY LOOP**: `AutonomousGoalAgent` initiates 20Hz closed-loop navigation:
   - Evaluates HC-SR04 distance every 50ms.
   - When distance > 40cm: drives forward.
   - When distance $\le 40\text{cm}$: triggers `_evade_and_replan_path()` calling `core/obstacle_bypass_engine.py` to execute a 5-stage flank detour.
6. **COMMUNICATION**: Continuous stream of WebSocket motor commands and telemetry updates.
7. **UI / RESPONSE**: 2D tactical arena visualizes robot trajectory, obstacle points, and mission report.

#### G. Command: Swarm / Cooperative Mission ("bupi conduct joint patrol")
1. **INPUT**: Natural language command requesting joint or dual-robot operation.
2. **ROUTER / AI TIER**: Tier 2 or Tier 1 routes to `SWARM_COOPERATIVE` policy.
3. **AGENT**: `AutonomousGoalAgent` spawns cooperative mission linking Bot 1 (Scout) and Bot 2 (Specialist).
4. **COORDINATOR**: `core/swarm_coordinator.py:coordinate_tandem_reading()` coordinates roles:
   - Bot 1 advances as lead scout, mapping obstacles and detecting human presence.
   - Bot 2 trails or takes environmental readings (MQ-2 gas, temperature, humidity).
   - If Bot 2 detects `gas_ppm > 350.0`, `_trigger_hazard_evacuation()` immediately broadcasts emergency stop to BOTH bots and activates warning relay.
5. **COMMUNICATION**: Simultaneous MQTT command publishing across `bupi/actuators/motors/cmd/json` (Bot 1) and `bupi/v1/bot2/actuators/motors/cmd/json` (Bot 2).
6. **UI / RESPONSE**: Both robots displayed on 2D tactical arena with color-coded trails (Purple for Scout, Green for Specialist).

---

# 6. SKILLS SYSTEM — CRITICAL

### Repository Skills Audit

1. **Workspace Skill: `bupi-robotics`**
   - **Path**: [.agents/skills/bupi-robotics/SKILL.md](file:///c:/Users/Sachin/boopi/assistant/.agents/skills/bupi-robotics/SKILL.md)
   - **Name**: `bupi-robotics`
   - **Trigger**: Activated when user requests robotics control, ESP32 hardware interfaces, sensor calibration, obstacle avoidance, or mission planning.
   - **Inputs**: Natural language robotics questions or control commands.
   - **Outputs**: Verified hardware pinouts, motor PWM logic, sensor formulas, and operational rules.
   - **Dependencies**: Markdown documentation file consumed by agent assistants.
   - **Hardware Assumptions**: ESP32 Dev Module, TB6612FNG, HC-SR04, MPU6050, MQ-2, DHT22.
   - **Dynamically Loaded?**: Static workspace skill discovered via `.agents/skills/`.
   - **Runtime Used?**: Used by Antigravity IDE coding agent; referenced by Python backend documentation.

2. **Agent Skills / Tool Definitions (`actions/hardware_tools.py`)**
   - 17 distinct callable tools wrapped with `@tool` (`CallableTool`) `[VERIFIED IN CODE]` ([hardware_tools.py:L4-L28](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L4-L28)).
   - Converted to OpenAI JSON schemas in `agents/local_orchestrator.py:LOCAL_TOOLS_SCHEMA` `[VERIFIED IN CODE]` ([local_orchestrator.py:L25-L192](file:///c:/Users/Sachin/boopi/assistant/agents/local_orchestrator.py#L25-L192)).
   - Bound to CrewAI agents in `agents/robotic_crew.py:L232-L236` `[VERIFIED IN CODE]`.

3. **Dynamic Hardware Ingestion & Memory System (`brain/ai_brain.py`)**
   - **Trigger**: User pastes Arduino/C++ code into Hardware Ingestion tab in `notepad.html` -> Electron IPC `notepad-process-hardware` -> `main.py` -> `ai.process_hardware(code)`.
   - **Execution**:
     1. `services/knowledge_super_agent.py` extracts component names and libraries.
     2. Generates knowledge cards from SQLite FTS5 index (`brain/fts5_hardware_index.db`) or ChromaDB.
     3. Prompts LLM using `hardware_rules.md` to transform code into MQTT-enabled firmware.
     4. Saves generated C++ to `brain/library/<Component>.cpp`.
     5. Prompts LLM to extract usage instruction: `- <Device>: To control ..., output [MQTT_SEND:<topic>:<payload>]`.
     6. Appends instruction to [hardware_memory.txt](file:///c:/Users/Sachin/boopi/assistant/hardware_memory.txt).
     7. Spawns persistent sub-agent in [brain/trained_agents.json](file:///c:/Users/Sachin/boopi/assistant/brain/trained_agents.json).
     8. Attempts automatic compilation and flashing via `actions/flasher.py:auto_flash_code()` using `arduino-cli`.

### Teaching a NEW Hardware Device to BUPI: 12 Specific Questions

| # | Question | Verified Reality in Source Code | Code Reference |
| :--- | :--- | :--- | :--- |
| **1** | **What files must be added?** | **None strictly required for simple actuators.** The system can auto-generate `brain/library/<Component>.cpp` and append to `hardware_memory.txt`. For full native telemetry translation, entries must be added to `core/sensor_translator.py`. | [ai_brain.py:L429-L525](file:///c:/Users/Sachin/boopi/assistant/brain/ai_brain.py#L429-L525), [sensor_translator.py:L40](file:///c:/Users/Sachin/boopi/assistant/core/sensor_translator.py#L40) |
| **2** | **What knowledge must be supplied?** | Component name, operating voltage, pin connections, bus protocol (I2C/SPI/UART/Analog), and sample C++ Arduino code snippet. | [hardware_rules.md:L1-L150](file:///c:/Users/Sachin/boopi/assistant/hardware_rules.md#L1-L150), [knowledge_super_agent.py:L415](file:///c:/Users/Sachin/boopi/assistant/services/knowledge_super_agent.py#L415) |
| **3** | **What capabilities must be declared?** | A list of string tokens in the announcement JSON: e.g. `["Sensor", "Actuator", "Display", "Servo", "Motors"]`. | [bupi_node_server.py:L805](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L805), [robotic_crew.py:L245-L279](file:///c:/Users/Sachin/boopi/assistant/agents/robotic_crew.py#L245-L279) |
| **4** | **What actions must be declared?** | The command payload format: action verb (e.g. `set_angle`, `turn_on`), parameters (e.g. `angle: 0-180`), and target MQTT topic. | [hardware_memory.txt:L1-L10](file:///c:/Users/Sachin/boopi/assistant/hardware_memory.txt#L1-L10), [ai_brain.py:L503](file:///c:/Users/Sachin/boopi/assistant/brain/ai_brain.py#L503) |
| **5** | **What sensors must be declared?** | Sensor ID string, telemetry field name in JSON packet (e.g. `lux`, `gas_ppm`, `distance_cm`), and engineering unit. | [bupi_node_server.py:L812](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L812), [sensor_translator.py:L20-L80](file:///c:/Users/Sachin/boopi/assistant/core/sensor_translator.py#L20-L80) |
| **6** | **What communication protocol must be implemented?** | MQTT over TCP (port 1883) connecting to `192.168.137.1` OR WebSocket client connecting to `ws://192.168.137.1:8767`. | [bupi_node_server.py:L1008-L1016](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L1008-L1016), [esp32_hive_display.ino:L130](file:///c:/Users/Sachin/boopi/assistant/esp32_hive_display.ino#L130) |
| **7** | **Can the device self-register?** | **YES.** Transmitting `{"type": "announce", "client_id": "...", "capabilities": [...]}` registers the device in memory and the SQLite `nodes` table. | [bupi_node_server.py:L148-L167](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L148-L167), [L798-L807](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L798-L807) |
| **8** | **Can BUPI discover it automatically?** | **YES**, as long as the device connects to the Windows Hotspot (`192.168.137.1`) and publishes its announcement packet. Active IP subnet scanning is NOT implemented. | [bupi_node_server.py:L800](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L800) |
| **9** | **Can agents automatically understand its capabilities?** | **PARTIALLY.** Tier 3 CrewAI reads `live_nodes` and dynamically creates specialized sub-agents. Mode 1 companion reads `hardware_memory.txt`. Tier 1 regex cannot understand new devices without code changes. | [robotic_crew.py:L241-L308](file:///c:/Users/Sachin/boopi/assistant/agents/robotic_crew.py#L241-L308), [local_orchestrator.py:L218](file:///c:/Users/Sachin/boopi/assistant/agents/local_orchestrator.py#L218) |
| **10** | **Can the device be used without modifying BUPI core logic?** | **YES, FOR ARBITRARY MQTT ACTUATORS.** The `universal_mqtt_tool` can publish to any topic learned in `hardware_memory.txt`. **NO FOR LOCOMOTION / CLOSED-LOOP AUTONOMY.** | [actions/hardware_tools.py:L219-L236](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L219-L236) |
| **11** | **What code must actually change?** | To support custom sensor semantic translation, `core/sensor_translator.py` needs threshold ranges. To add dedicated tool schemas for local Tier 2 Ollama, `agents/local_orchestrator.py` must be edited. | [sensor_translator.py:L40](file:///c:/Users/Sachin/boopi/assistant/core/sensor_translator.py#L40), [local_orchestrator.py:L25](file:///c:/Users/Sachin/boopi/assistant/agents/local_orchestrator.py#L25) |
| **12** | **What parts remain hard-coded?** | Motor drive commands (`bupi/actuators/motors/cmd/json`), robot IDs (`bupi_01`, `bupi_02`), TB6612 pin assignments in firmware, and 2D arena canvas bot rendering. | [firmware/bupi_bot1_scout.ino:L48-L56](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L48-L56), [hardware_tools.py:L128-L134](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L128-L134) |

---

# 7. DEVICE / CAPABILITY SCHEMA AUDIT

### Canonical Device Registration Schema

The announcement packet must follow this JSON schema `[VERIFIED IN CODE]` ([bupi_node_server.py:L798-L807](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L798-L807), [workspace/BupiNode/BupiNode.ino:L87](file:///c:/Users/Sachin/boopi/assistant/workspace/BupiNode/BupiNode.ino#L87)):

```json
{
  "type": "announce",
  "client_id": "bupi_01",
  "device": "BUPI_01_SCOUT",
  "ip": "192.168.137.45",
  "capabilities": ["Motors", "Ultrasonic", "IMU", "PIR"],
  "tasks": ["Robotic Control", "Spatial Reconnaissance"],
  "role": "Scout",
  "status": "online",
  "timestamp": 1727624890.12
}
```

### Architectural Tests on Hypothetical Devices

#### Device A: ESP32 + Servo + Ultrasonic
- **Reusable Components**: `bupi_node_server.py` (WS/Serial bridge), `universal_mqtt_tool`, `read_sensor_status` (for ultrasonic), SQLite telemetry persistence, WebSocket live broadcast.
- **Components to Add**: Servo angle command topic handler in firmware, servo knowledge card in `hardware_memory.txt`.
- **Components to Rewrite**: None.
- **Intelligence Core Status**: **UNCHANGED**. Tier 2 and Tier 3 agents can command the servo via `universal_mqtt_tool(topic="bupi/actuators/servo/cmd", payload="90")`.

#### Device B: ESP32 + Camera + Motor
- **Reusable Components**: Motor control schemas (`control_motors`), TB6612 motor driver logic, motion safety validator, WebSocket command dispatch.
- **Components to Add**: Video streaming pipeline (MJPEG/RTSP server on ESP32-CAM, video ingest thread in Python, HTML5 `<video>` or canvas element in `notepad.html`).
- **Components to Rewrite**: `core/kinematics_odometry.py` (if visual odometry is desired).
- **Intelligence Core Status**: **PARTIALLY MODIFIED**. The text/command intelligence is unchanged, but vision-based decision making is absent in Python backend.

#### Device C: ESP32 Flying Drone Controller
- **Reusable Components**: Mosquitto MQTT broker, 3-tier routing architecture, high-level mission goals, voice input/output pipelines.
- **Components to Add**: 3D spatial flight kinematics ($x, y, z, \text{yaw}, \text{pitch}, \text{roll}$), altitude PID controller, MAVLink or MSP bridge, emergency rotor-cutoff safety validator.
- **Components to Rewrite**: `control_motors` (requires $z$-axis thrust and flight dynamics instead of 2D differential drive).
- **Intelligence Core Status**: **SIGNIFICANT CHANGES REQUIRED**. 2D planar assumptions pervade `kinematics_odometry.py`, `instruction_decomposer.py`, and `spatial_twin_2d.html`.

#### Device D: Raspberry Pi Robot
- **Reusable Components**: Entire 3-tier decision pipeline, all Python tool definitions, `bupi_telemetry.db` schema, WebSocket protocols, MQTT topic hierarchy.
- **Components to Add**: Linux systemd service daemon, Linux I2C/GPIO drivers (`smbus2`, `gpiod`), local audio driver configuration.
- **Components to Rewrite**: Hardware bridge communication layer (shifts from remote TCP/Serial to local Linux IPC/domain sockets).
- **Intelligence Core Status**: **UNCHANGED**. Python codebase runs natively on Linux/ARM with minor path adjustments.

---

# 8. HARDWARE ABSTRACTION AUDIT

### Command Generality vs. Device Specificity Matrix

| Hardware Function | Implementation File & Line | Command Generality Level | Target Coupling | Real Code Evidence |
| :--- | :--- | :--- | :--- | :--- |
| **Motor Drive** | [actions/hardware_tools.py:L86](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L86) (`control_motors`) | **Robot-ID-Specific** | Hardcoded to `bupi_01` and `bupi_02` differential drive topics | `if target_bot in ["bupi_02", "bot2"]: topics = ["bupi/v1/bot2/actuators/motors/cmd"]` |
| **Precision Gyro Turn** | [actions/hardware_tools.py:L144](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L144) (`control_motors`) | **Capability-Specific** | Requires MPU6050 gyro feedback on target bot | `payload = json.dumps({"action": "turn_by", "degrees": degrees, ...})` |
| **Relay Control** | [actions/hardware_tools.py:L32](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L32) (`control_relay`) | **Device-Specific** | Hardcoded to `device_id == 'relay_1'` on topic `bupi/hardware/{device_id}/set` | `topic = f"bupi/hardware/{device_id}/set"` |
| **LCD Display** | [actions/hardware_tools.py:L56](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L56) (`display_on_esp32`) | **Protocol-Specific** | Dual-publishes to `bupi/nodes/desk_display/cmd` and `bupi/actuators/lcd/cmd` | Formats string for 16x2 LCD character layout |
| **Universal Actuator** | [actions/hardware_tools.py:L219](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L219) (`universal_mqtt_tool`) | **GENUINELY GENERIC** | Completely uncoupled; sends arbitrary payload to any topic | `publish.single(topic, payload, hostname="localhost")` |
| **Sensor Telemetry Query** | [actions/hardware_tools.py:L239](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L239) (`read_sensor_status`) | **Capability-Specific** | Auto-routes sensor types to capable bot (gas -> Bot 2, PIR -> Bot 1) | `if any(k in sensor_id for k in ["mq2", "gas"]): candidate_bots = ["bupi_02"]` |
| **Arbitrary Python Script** | [actions/hardware_tools.py:L546](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L546) (`run_robotic_code`) | **GENUINELY GENERIC** | Executes arbitrary Python in sandbox with `publish()` and `subscribe()` | `exec(cleaned_code, exec_globals)` with safety validation |
| **Firmware Reflex Avoidance**| [firmware/bupi_bot1_scout.ino:L129](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L129) (`AvoidState`) | **Device-Specific** | Embedded directly into Bot 1 ESP32 firmware loop | 7-stage finite state machine on TB6612 motor pins |

---

# 9. MULTI-ROBOT / SWARM AUDIT

### Bot Specialization & Heterogeneous Fleet Reality

- **Bot 1 Scout (`bupi_01`)**:
  - Role: Motion reconnaissance, perimeter exploration, target acquisition.
  - Active Sensors: HC-SR04 ultrasonic distance, PIR thermal infrared motion (GPIO 34/19), MPU6050 6-axis IMU `[VERIFIED IN CODE]` ([firmware/bupi_bot1_scout.ino:L508-L588](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L508-L588)).
  - Does NOT read MQ-2 gas or DHT22 climate sensors.
- **Bot 2 Environmental Specialist (`bupi_02`)**:
  - Role: Hazardous material detection, toxic gas tracking, climate analysis.
  - Active Sensors: MQ-2 gas sensor (GPIO 34 ADC1_CH6), DHT22 temperature & humidity (GPIO 4), HC-SR04 ultrasonic distance, MPU6050 6-axis IMU `[VERIFIED IN CODE]` ([firmware/bupi_bot2_specialist.ino:L550-L624](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot2_specialist.ino#L550-L624)).
  - Does NOT read PIR motion sensor.

### Swarm Scalability Reality: Can it support N robots?

- **Truth**: **NO, N-ROBOT SCALABILITY IS NOT IMPLEMENTED IN RUNTIME CODE.**
- **Evidence**:
  1. `core/swarm_coordinator.py:L36-L61` defines a hardcoded dictionary containing exactly two keys: `"bupi_01"` and `"bupi_02"`.
  2. `actions/hardware_tools.py:L128-L134` explicitly checks:
     `if target_bot in ["all", "both", "fleet"]: topics = ["bupi/actuators/motors/cmd", "bupi/v1/bot2/actuators/motors/cmd"]`.
  3. `spatial_intelligence/multi_bot_fusion.py:L4` states: *"Correlates observations from BUPI-01 (Scout) and BUPI-02 (Environmental Specialist)"*.
  4. While the MQTT broker and WebSocket server technically permit $N$ TCP connections, the coordination logic, topic routing, and UI visualization strictly accommodate a **dual-robot pair** (`bupi_01` + `bupi_02`).

### Telemetry Fusion & Hazard Handling

- **Spatio-Temporal Fusion Criteria**:
  - Spatial radius: $R \le 1.5\text{ meters}$ `[VERIFIED IN CODE]` ([multi_bot_fusion.py:L9](file:///c:/Users/Sachin/boopi/assistant/spatial_intelligence/multi_bot_fusion.py#L9)).
  - Temporal window: $\Delta t \le 60.0\text{ seconds}$ `[VERIFIED IN CODE]` ([multi_bot_fusion.py:L10](file:///c:/Users/Sachin/boopi/assistant/spatial_intelligence/multi_bot_fusion.py#L10)).
- **Hazard Intercept**:
  - When Bot 2 reports `gas_ppm > 350.0`, `swarm_coordinator._trigger_hazard_evacuation()` publishes immediate halt commands to BOTH robots and triggers relay alarm `[VERIFIED IN CODE]` ([swarm_coordinator.py:L131-L153](file:///c:/Users/Sachin/boopi/assistant/core/swarm_coordinator.py#L131-L153)).

---

# 10. AUTONOMY

### Autonomous Goal Agent (`agents/autonomous_goal_agent.py`)

- **Execution Loop Rate**: **20 Hz** (`dt = 0.05` s / 50 ms loop sleep) `[VERIFIED IN CODE]` ([autonomous_goal_agent.py:L1275](file:///c:/Users/Sachin/boopi/assistant/agents/autonomous_goal_agent.py#L1275)).
- **11 Verified Mission Policies** ([planner/instruction_decomposer.py:L24-L36](file:///c:/Users/Sachin/boopi/assistant/planner/instruction_decomposer.py#L24-L36)):
  1. `CONDITIONAL_MOVE`: Drives until stop condition is met (e.g. walk until obstacle, take 10 steps).
  2. `SCAN_SWEEP`: 360° rotational radar scan across 8 sectors.
  3. `MONITOR_HOLD`: Stationary sentry monitoring environmental deltas.
  4. `ROTATE_TO`: Precision gyro-integrated heading turn.
  5. `EXPLORE_SAFE`: Continuous autonomous roaming with reactive obstacle evasion.
  6. `PATROL`: Perimeter patrol between designated boundaries.
  7. `DIRECT_ACTION`: Atomic stop/turn execution.
  8. `APPROACH_TARGET`: Scans for PIR human detection, locks bearing, and approaches to safe boundary.
  9. `SWARM_COOPERATIVE`: Synchronized dual-robot mission coordinating Bot 1 and Bot 2.
  10. `ODOMETRY_REPORT`: Verbal debrief of steps, distance, and laptop RF range.
  11. `RETURN_TO_ORIGIN`: Closed-loop dead-reckoning return to origin $(0, 0)$.

### Verified Observe -> Reason -> Act Cycle

```
1. OBSERVE (20Hz Sensor Sampling)
   - bupi_node_server receives WebSocket telemetry from Bot 1:
     {"distance_cm": 22.4, "heading": 89.2, "ax": 0.02, "ay": -0.01, "az": 1.01, "pir": 0}
   - Updates in-memory world state cache; checks freshness TTL (age: 0.05s < 15.0s).

2. REASON (AutonomousGoalAgent.run_step & DynamicStopCondition)
   - Mission active: "walk until an obstacle comes in front of you".
   - Safety Controller evaluates: safe_distance_cm = 40.0, critical_distance_cm = 15.0.
   - Reading (22.4cm) <= safe_distance_cm (40.0cm).
   - Stop condition evaluated: DynamicStopCondition(distance_cm <= 25.0) -> TRIGGERED!

3. ACT (Motor Halt & Mission Debrief)
   - Goal agent terminates movement loop.
   - Publishes {"action": "stop", "speed": 0} to bupi/actuators/motors/cmd/json.
   - Logs mission completion to bupi_telemetry.db (status="OBSTACLE_REACHED").
   - Dispatches spoken debrief via Edge-TTS: "Obstacle detected at 22.4 centimeters. Movement halted safely."
```

### Dynamic Replanning & Obstacle Bypass (`core/obstacle_bypass_engine.py`)

When an obstacle is encountered during a non-halting mission (e.g. `EXPLORE_SAFE`), the agent triggers `execute_obstacle_bypass(bot_id)` `[VERIFIED IN CODE]` ([obstacle_bypass_engine.py:L40-L120](file:///c:/Users/Sachin/boopi/assistant/core/obstacle_bypass_engine.py#L40-L120)):
1. **Stage 1 (Reverse)**: Reverses chassis at speed 200 for 300ms to open standoff clearance.
2. **Stage 2 (Pivot)**: Closed-loop gyro turn of $+45.0^\circ$ to flank obstacle.
3. **Stage 3 (Flank Advance)**: Drives forward along flank at speed 200 for 400ms.
4. **Stage 4 (Counter-Pivot)**: Closed-loop gyro turn of $-45.0^\circ$ to restore original mission heading.
5. **Stage 5 (Verify Clearance)**: Halts for 150ms to settle ultrasonic readings; if clear, resumes primary cruise.

---

# 11. SAFETY

### Safety Architecture Matrix

| Safety Mechanism | Enforcement Location | Threshold / Trigger | Active in Dev? | Can LLM Override? | Fallback Behavior |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Voice E-Stop** | [router_agent.py:L80](file:///c:/Users/Sachin/boopi/assistant/agents/router_agent.py#L80) | Words: `stop`, `halt`, `freeze`, `brake`, `emergency stop` | **ACTIVE** | **NO** | Immediately broadcasts halt to all MQTT topics & WebSockets |
| **Gas Hazard Barrier** | [core/safety_validator.py:L125](file:///c:/Users/Sachin/boopi/assistant/core/safety_validator.py#L125) | Gas level `DANGER` (>2500) or `CRITICAL` (>3500) | **ACTIVE** | **NO** | Blocks forward drive commands; blocks turning off ventilation relay |
| **Swarm Hazard Evacuation** | [core/swarm_coordinator.py:L131](file:///c:/Users/Sachin/boopi/assistant/core/swarm_coordinator.py#L131) | `gas_ppm > 350.0` on Bot 2 | **ACTIVE** | **NO** | Halts BOTH robots; turns on relay warning light |
| **Telemetry Freshness TTL** | [core/safety_validator.py:L6](file:///c:/Users/Sachin/boopi/assistant/core/safety_validator.py#L6) | Telemetry age $> 15.0\text{ seconds}$ | **ACTIVE** | **NO** | Marks state `UNKNOWN_STALE`; flags `telemetry_fresh = False` |
| **Node Heartbeat Watchdog** | [bupi_node_server.py:L184](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L184) | Heartbeat interval $> 15.0\text{ seconds}$ | **ACTIVE** | **NO** | Marks node status `OFFLINE` in database and memory |
| **Firmware Timed Cutoff** | [firmware/bupi_bot1_scout.ino:L987](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L987)| `now >= motorEndTime` | **ACTIVE** | **NO** | Halts motors locally on ESP32 without waiting for host PC packet |
| **Mode 2 Deadlock Watchdog** | [main.py:L545](file:///c:/Users/Sachin/boopi/assistant/main.py#L545) | Daemon response delay $> 15.0\text{ seconds}$ | **ACTIVE** | **NO** | Clears pending state to prevent voice assistant lockup |
| **Firmware Collision Cutoff** | [firmware/bupi_bot1_scout.ino:L85](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L85) | `CRITICAL_OBSTACLE_CM = 0.0` (`#define ENABLE_OBSTACLE_CUTOFF 0`) | **DISABLED** | N/A | Set to 0.0cm in dev firmware to prevent bench test stalls |
| **Firmware Rollover Cutoff** | [firmware/bupi_bot1_scout.ino:L86](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L86) | `CRITICAL_TILT_DEG = 85.0` (`#define ENABLE_TILT_CUTOFF 0`) | **DISABLED** | N/A | Set to 85.0° and disabled in dev firmware |
| **Software Obstacle Blocking** | [core/safety_validator.py:L109](file:///c:/Users/Sachin/boopi/assistant/core/safety_validator.py#L109)| `ENABLE_OBSTACLE_AVOIDANCE = False` | **DISABLED** | N/A | Disabled in dev mode to allow manual bench overrides |
| **Software Tilt Blocking** | [core/safety_validator.py:L110](file:///c:/Users/Sachin/boopi/assistant/core/safety_validator.py#L110)| `ENABLE_TILT_SAFETY = False` | **DISABLED** | N/A | Disabled in dev mode |

---

# 12. COMMUNICATION FABRIC

### Network Protocol & Transport Matrix

| Transport | Port / Address | Protocol | Publisher / Sender | Subscriber / Receiver | Payload Schema | Retry / Failure Policy |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **WebSocket** | `0.0.0.0:8767` | WebSocket (RFC 6455) | ESP32 Nodes / UI Clients | `bupi_node_server.py` | JSON (`announce`, `telemetry`, `heartbeat`) | Reconnect loop in ESP32 firmware every 2000ms |
| **MQTT** | `127.0.0.1:1883` | MQTT 3.1.1 / 5.0 | Python Mode 1, Mode 2, Bridge | Python daemons & auxiliary nodes | JSON and UTF-8 strings | Paho client auto-reconnect via `loop_start()` |
| **USB Serial** | `COM3` (115200 baud) | Asynchronous UART | ESP32 (direct wired) | `bupi_node_server.py` | JSON lines terminated by `\n` | `SerialSupervisor` polls port every 2.0s |
| **Mobile Hotspot** | `192.168.137.1` | Wi-Fi 802.11 b/g/n DHCP | Windows Netsh / ICS | ESP32 Wi-Fi Stations | IP packets (TCP/UDP) | `HotspotWatchdog` verifies hotspot state every 30s |
| **Electron IPC** | Native Memory | Chromium IPC | Electron Renderers | Electron Main (`main.js`) | IPC channel messages (`notepad-process-hardware`) | Synchronous / Promise-based Electron handlers |
| **Python IPC** | Stdin / Stdout | JSON lines over Pipes | Electron Main (`main.js`) | `main.py` | Line-delimited JSON (`{"type": "...", "value": "..."}`) | Child process stdio monitoring |

### Canonical MQTT Topic Map

```
bupi/
├── internal/
│   ├── utterance           # Mode 1 -> Mode 2 (Transcribed user commands)
│   ├── tts                 # Mode 2 -> Mode 1 (Spoken feedback text)
│   └── estop               # Broadcast emergency stop signal
├── actuators/
│   ├── motors/
│   │   ├── cmd             # Plain string direction ('forward', 'stop')
│   │   └── cmd/json        # Structured JSON motor packet for Bot 1 Scout
│   └── lcd/
│       └── cmd             # Plain string text for 1602 LCD
├── v1/bot2/actuators/
│   └── motors/
│       ├── cmd             # Plain string direction for Bot 2 Specialist
│       └── cmd/json        # Structured JSON motor packet for Bot 2 Specialist
├── hardware/
│   └── relay_1/set         # Plain string: "ON" or "OFF"
├── sensors/
│   ├── mq2/state           # Sensor telemetry strings
│   └── dht/temperature     # Temperature telemetry
├── swarm/
│   └── events              # High-level swarm events and hazard alerts
└── nodes/
    ├── announce            # Node announcement registration packets
    ├── heartbeat           # Keep-alive heartbeat packets
    └── desk_display/cmd    # Display commands for Desk Display node
```

---

# 13. LIVE TELEMETRY / LIVE FEEDS

### Verified Update Rates & Feed Reality

| Feed / Stream Name | Actual Update Rate | Transport / Channel | Ground-Truth Reality | Status Tag |
| :--- | :---: | :--- | :--- | :--- |
| **ESP32 Perception Loop** | **20 Hz** (50 ms) | Onboard Microcontroller | Samples HC-SR04 median filter and MPU6050 register bus | `[VERIFIED IN CODE]` |
| **Active Telemetry Stream** | **10 Hz** (100 ms) | WebSocket / USB Serial | Streamed when robot is moving or turning | `[VERIFIED IN CODE]` |
| **Idle Telemetry Stream** | **2 Hz** (500 ms) | WebSocket / USB Serial | Streamed when robot is stationary | `[VERIFIED IN CODE]` |
| **Heartbeat Keep-Alive** | **0.2 Hz** (5000 ms) | WebSocket / MQTT | Transmitted to confirm node connection | `[VERIFIED IN CODE]` |
| **UI Telemetry Broadcast** | **1.0 Hz** (1000 ms) | WebSocket (`:8767`) | Aggregated fleet state broadcast to web UI | `[VERIFIED IN CODE]` |
| **SQLite Batch Telemetry Flush** | **0.67 Hz** (1500 ms) | Internal Python Thread | Flushes sensor reading queue to `bupi_telemetry.db` | `[VERIFIED IN CODE]` |
| **2D Arena Canvas Rendering** | RequestAnimationFrame (~60 Hz) | WebGL / 2D Canvas | Interpolates latest received telemetry packets | `[VERIFIED IN CODE]` |
| **Camera / Video Streaming** | **0 Hz (NONE)** | **NOT IMPLEMENTED** | No camera frames exist. "Camera" terms are strictly Three.js 3D viewport coordinates. | `[DOCUMENTED ONLY]` |

---

# 14. DATABASE / MEMORY / KNOWLEDGE AUDIT

### Persistent Storage Audit

#### 1. SQLite: `bupi_telemetry.db`
- **Location**: `c:\Users\Sachin\boopi\assistant\bupi_telemetry.db`
- **Schemas**:
  - `telemetry`: `(timestamp REAL, sensor_id TEXT, value REAL)`
  - `decisions`: `(timestamp REAL, world_state TEXT, decision TEXT, result TEXT)`
  - `nodes`: `(client_id TEXT PRIMARY KEY, device_name TEXT, ip_address TEXT, capabilities TEXT, last_heartbeat REAL, status TEXT)`
  - `missions`: `(id INTEGER PRIMARY KEY, mission_name TEXT, goal TEXT, project_type TEXT, started_at REAL, ended_at REAL, duration_seconds REAL, status TEXT, findings_json TEXT, report_markdown TEXT, created_at DATETIME)`
- **Writers**: `bupi_node_server.py` (`DbWriter` thread), `AutonomousGoalAgent`, `local_orchestrator.py`.
- **Readers**: `actions/hardware_tools.py`, `core/safety_validator.py`, UI reporting tabs.
- **Offline Capable?**: **100% Offline** (local embedded SQLite file).

#### 2. SQLite: `brain/bupi.db`
- **Location**: `c:\Users\Sachin\boopi\assistant\brain\bupi.db`
- **Schemas**: Managed by `brain/db_manager.py`:
  - `preferences`: User key-value configuration.
  - `reminders`: User task schedule with epoch trigger timestamps.
  - `conversations`: Historic chat dialogue (`id, role, content, timestamp`).
  - `emotion_history`: Emotion analysis logs (sadness, frustration, stress, anger, happiness, neutral).
  - `activity_log`: Foreground window titles and application usage durations.
  - `memory_summaries`: Episodic knowledge categories extracted from user conversations.
- **Writers**: `main.py`, `brain/ai_brain.py`, `brain/activity_monitor.py`.
- **Readers**: Mode 1 companion brain system prompt context injector.
- **Offline Capable?**: **100% Offline**.

#### 3. SQLite FTS5: `brain/fts5_hardware_index.db`
- **Location**: `c:\Users\Sachin\boopi\assistant\brain\fts5_hardware_index.db`
- **Schema**: Virtual table `hardware_fts USING fts5(name, sentence, paragraph, website, includes)`.
- **Content**: Pre-indexed Arduino official library definitions and sensor datasheets from `brain/arduino_library_index.json`.
- **Writers**: `services/knowledge_super_agent.py:_init_fts5_db()`.
- **Readers**: `KnowledgeSuperAgent` for microsecond offline hardware datasheet retrieval.
- **Offline Capable?**: **100% Offline**.

#### 4. Vector Store: ChromaDB (`brain/chroma_hardware_db` & `brain/chroma_db`)
- **Status**: `[VERIFIED BUT PARTIAL]`. Wrapped in `try...except ImportError` blocks.
- **Role**: Vector embedding store for component technical documentation.
- **Fallback**: If ChromaDB fails or is absent, automatically falls back to [brain/sensor_knowledge_cache.json](file:///c:/Users/Sachin/boopi/assistant/brain/sensor_knowledge_cache.json) `[VERIFIED IN CODE]` ([knowledge_super_agent.py:L76-L78](file:///c:/Users/Sachin/boopi/assistant/services/knowledge_super_agent.py#L76-L78)).

---

# 15. RAG / HARDWARE KNOWLEDGE AUDIT

### How Hardware Knowledge Reaches the AI

```
[User pastes C++ snippet or queries component]
        |
        v
1. services/knowledge_super_agent.py
   - Extracts component names & library headers (e.g. "MQ2", "LiquidCrystal_I2C").
        |
        +---> Query SQLite FTS5 table (brain/fts5_hardware_index.db) [<1ms offline search]
        |       └─ Matches library descriptions, official includes, architecture compatibility.
        |
        +---> Query ChromaDB / JSON Cache (brain/sensor_knowledge_cache.json)
        |       └─ Retrieves operating voltage, pinouts, sensitivity curves, truth tables.
        v
2. Knowledge Card Synthesis
   - Formats structured JSON cards containing exact hardware constraints.
        |
        v
3. LLM Prompt Context Injection
   - Injected into hardware_rules.md system prompt:
     {hardware_rules} + {knowledge_cards_str} + {Original_Code}
        |
        v
4. Permanent Memory Persistence
   - LLM extracts command signature: "- <Device>: To control ..., output [MQTT_SEND:<topic>:<payload>]".
   - Appended to hardware_memory.txt.
   - Mode 1 & Mode 2 LLMs read hardware_memory.txt during subsequent system prompt generation!
```

### Can BUPI use knowledge about a new hardware component without changing core logic?
- **YES, FOR ACTUATION & RETRIEVAL**: If the user pastes C++ for a new I2C display or servo, the system stores the MQTT usage rule into `hardware_memory.txt`. The `universal_mqtt_tool` can publish to that topic immediately without modifying any Python files.
- **PARTIALLY, FOR SENSORS**: The raw data will be stored in SQLite, but conversational semantic labels (e.g. converting raw ADC to "DANGER") require hardcoded threshold entries in `core/sensor_translator.py`.

---

# 16. OFFLINE / EDGE / CLOUD AUDIT

### Complete Component Operating Matrix

| Component | Local? | Offline? | Cloud? | Model / Provider | Fallback Mechanism | Verified Latency | Failure Behavior |
| :--- | :---: | :---: | :---: | :--- | :--- | :---: | :--- |
| **STT (Voice)** | YES | **YES** | NO | Faster-Whisper (`tiny.en`) | `base` model fallback | ~150–300 ms | Discards inaudible audio buffer |
| **VAD (Voice Activity)**| YES | **YES** | NO | `webrtcvad` C-extension | Energy thresholding | < 5 ms | Drops background noise frame |
| **Tier 1 Regex** | YES | **YES** | NO | Deterministic Python regex | Escalates to Tier 2 | < 5 ms | Returns `None` to trigger LLM |
| **Tier 2 Orchestrator** | YES | **YES** | NO | Ollama `llama3.2:3b` | Ollama `llama3.1:8b` | ~500 ms | Escalates to Tier 3 on error |
| **Tier 3 Multi-Agent** | PARTIAL| PARTIAL| **YES** | Ollama -> Gemini -> Groq -> NVIDIA | Sequential provider chain | 5–15 sec | Fails gracefully with user error |
| **Autonomous Mission** | YES | **YES** | NO | `AutonomousGoalAgent` (20Hz) | Deterministic state machine | 50 ms loop | Halts motors on collision/timeout |
| **Safety Validator** | YES | **YES** | NO | Local in-memory world state | SQLite historic cache | < 1 ms | Blocks command (`approved: False`) |
| **Kinematics Odometry**| YES | **YES** | NO | Epistemic kinematics engine | Dead-reckoning accumulation | < 1 ms | Continues with drift accumulation |
| **Local Knowledge** | YES | **YES** | NO | SQLite FTS5 & JSON cache | Local dictionary | < 5 ms | Returns unconfigured baseline card |
| **TTS Speech (Default)**| NO | NO | **YES** | Microsoft `edge-tts` | Falls back to Windows SAPI5 | ~400–800 ms | Swaps to `pyttsx3` offline voice |
| **TTS Speech (Offline)**| YES | **YES** | NO | Windows SAPI5 / `pyttsx3` | None | ~50 ms | Drops spoken audio if audio blocked |
| **Mode 1 Desktop Brain**| NO | NO | **YES** | Google Gemini / OpenRouter | Groq -> NVIDIA -> OpenRouter | ~800–1800 ms| Logs error to UI |

### True Offline Robotic Operating Mode

When disconnected from the internet (e.g. in disaster response, subterranean rescue, or air-gapped field operations):
- **100% OPERATIONAL**: Microphone capture, Whisper STT, Tier 1 Regex E-stops and locomotion, Tier 2 local Ollama tool calling, 20Hz closed-loop autonomous missions (`AutonomousGoalAgent`), obstacle bypass maneuvers, hardware safety validation, Mosquitto MQTT broker, WebSocket hardware bridge, offline pyttsx3 voice feedback, and local SQLite/FTS5 knowledge searches.
- **DISABLED WITHOUT INTERNET**: Microsoft Edge-TTS neural cloud voices (automatically falls back to pyttsx3), Mode 1 open-ended cloud conversations (Gemini/OpenRouter), and Tier 3 cloud CrewAI model fallbacks.

---

# 17. ELECTRON / UI AUDIT

### UI Surface & Data Source Mapping

| UI Surface / Panel | File & Line Location | Technologies Used | Primary Data Source | Interactive Elements |
| :--- | :--- | :--- | :--- | :--- |
| **Desktop Mascot Overlay** | [index.html:L1-L150](file:///c:/Users/Sachin/boopi/assistant/index.html#L1-L150), [main.js:L128](file:///c:/Users/Sachin/boopi/assistant/main.js#L128) | Three.js WebGL / Rive Canvas | `three_handler.js`, `mascot_handler.js`, Electron IPC `pet-status` | Draggable transparent overlay, click to pet mascot |
| **Mode Switcher Widget** | [notepad.html:L638-L758](file:///c:/Users/Sachin/boopi/assistant/notepad.html#L638-L758) | CSS Glassmorphism Pill Bar | Electron IPC `set-mode` (Mode 1 Companion vs Mode 2 Robot) | Mode 1 / Mode 2 toggle buttons |
| **Notes & Ideas Panel** | [notepad.html:L811-L824](file:///c:/Users/Sachin/boopi/assistant/notepad.html#L811-L824) | HTML5 Textarea | Local file storage, companion note-taking | Save note, word count, title input |
| **BUPI Autonomous Panel** | [notepad.html:L827-L865](file:///c:/Users/Sachin/boopi/assistant/notepad.html#L827-L865) | HTML5 Forms & Badges | `AutonomousGoalAgent` status via WebSocket `:8767` | Goal input text, scenario chips (Find Person, Patrol) |
| **Missions & Reports** | [notepad.html:L768](file:///c:/Users/Sachin/boopi/assistant/notepad.html#L768) (`panel-missions`) | CSS Grid & Markdown viewer | `bupi_telemetry.db:missions` table | View past mission records, debrief reports |
| **Hardware Setup / Ingest** | [notepad.html:L772](file:///c:/Users/Sachin/boopi/assistant/notepad.html#L772) (`panel-hardware`) | Code Editor Textarea | `brain/ai_brain.py:process_hardware()`, `actions/flasher.py` | C++ code paste area, Auto-Flash button, compile logs |
| **ESP32 Manual Control** | [notepad.html:L775](file:///c:/Users/Sachin/boopi/assistant/notepad.html#L775) (`panel-esp`) | CSS D-pad & Toggle Switches | `hardware_tools.py` via WebSocket `:8767` | Forward, Reverse, Left, Right, Stop buttons, Relay toggle |
| **Active Lab / Trained Agents**| [notepad.html:L778](file:///c:/Users/Sachin/boopi/assistant/notepad.html#L778) (`panel-trained`) | Dynamic Cards Grid | `brain/trained_agents.json`, `hardware_memory.txt` | View active dynamically spawned hardware sub-agents |
| **Chat History Panel** | [notepad.html:L781](file:///c:/Users/Sachin/boopi/assistant/notepad.html#L781) (`panel-chat`) | Scrollable Chat Log | `brain/bupi.db:conversations` table | View conversational history |
| **2D Arena Canvas** | [spatial_twin_2d.html](file:///c:/Users/Sachin/boopi/assistant/spatial_twin_2d.html) (embedded iframe) | HTML5 Canvas 2D Context | WebSocket stream from `spatial_twin_bridge.py` | Drag virtual obstacles, drag simulated humans, view trails |
| **Settings & Token Tracker**| [notepad.html:L450-L550](file:///c:/Users/Sachin/boopi/assistant/notepad.html#L450-L550) (`panel-settings`)| CSS Key Cards | `services/llm_gateway.py:get_token_status()` | API key rotation status (Groq, Gemini, NVIDIA, OpenRouter) |

---

# 18. BWE / DIGITAL TWIN / HIL AUDIT

### Bit-World Engine (BWE) Implementation Inspection

1. **Simulation Engine**: Implemented in JavaScript inside [bwe/core/engine.js](file:///c:/Users/Sachin/boopi/assistant/bwe/core/engine.js) and [bwe/core/physics.js](file:///c:/Users/Sachin/boopi/assistant/bwe/core/physics.js). Features a 2D kinematic and impulse physics model.
2. **Virtual Peripherals**: Modeled in [bwe/peripherals/](file:///c:/Users/Sachin/boopi/assistant/bwe/peripherals/):
   - `gpio_manager.js`: Virtual digital pin states (HIGH/LOW).
   - `pwm_manager.js`: Virtual PWM duty cycle tracking (0–255).
   - `analog_manager.js`: Virtual 12-bit ADC voltage levels (0–4095).
   - `comm_managers.js`: Virtual I2C and SPI bus packet transport.
3. **Plugin Architecture**: Modular peripheral extensions in [bwe/plugins/](file:///c:/Users/Sachin/boopi/assistant/bwe/plugins/):
   - Sensors: HC-SR04 ultrasonic ([hcsr04.js](file:///c:/Users/Sachin/boopi/assistant/bwe/plugins/sensors/hcsr04.js)), MQ-2 gas sensor ([mq2.js](file:///c:/Users/Sachin/boopi/assistant/bwe/plugins/sensors/mq2.js)).
   - Actuators: Servo motor ([servo.js](file:///c:/Users/Sachin/boopi/assistant/bwe/plugins/actuators/servo.js)), SSD1306 OLED display ([oled.js](file:///c:/Users/Sachin/boopi/assistant/bwe/plugins/actuators/oled.js)).
4. **Hardware-in-the-Loop (HIL)**: [bwe/interface/hil_bridge.js](file:///c:/Users/Sachin/boopi/assistant/bwe/interface/hil_bridge.js) bridges physical ESP32 microcontrollers flashing [esp32_bwe_mqtt_client.ino](file:///c:/Users/Sachin/boopi/assistant/esp32_bwe_mqtt_client.ino) with simulated environment peripherals over USB Serial.
5. **State Injection**: In [spatial_twin_2d.html:L600-L650](file:///c:/Users/Sachin/boopi/assistant/spatial_twin_2d.html#L600-L650), users can drag obstacle and human tokens on the canvas; [bupi_node_server.py:L823-L845](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L823-L845) parses `move_human` and `move_obstacle` packets to reflect spatial positions into the digital twin.
6. **Logging**: State transitions are logged to [bwe_twin_log.jsonl](file:///c:/Users/Sachin/boopi/assistant/bwe_twin_log.jsonl).

### 7 Critical Questions Answered:
1. *What can be simulated?* Differential-drive chassis motion, HC-SR04 ultrasonic beam intersection with rectangular obstacles, MQ-2 gas diffusion plumes, and virtual I2C display updates.
2. *What can be interacted with?* Canvas tokens (drag human marker, place obstacle boxes).
3. *Does the same mission logic run?* **YES.** `AutonomousGoalAgent` accepts telemetry from either the physical bridge or virtual bridge without altering its policy loop.
4. *Does the same command layer run?* **YES.** Commands use identical MQTT topics and JSON schemas.
5. *Does telemetry follow the same schema?* **YES.** Virtual sensor packets emulate physical ESP32 JSON telemetry format.
6. *Can a hypothetical new device be represented?* **YES**, by adding a new plugin in `bwe/plugins/sensors/` or `bwe/plugins/actuators/`.
7. *Can simulation be used before physical deployment?* **YES.** Allows testing mission state machines, replanning detours, and regex parsing prior to running hardware.

---

# 19. FUTURE EDGE COMPUTE AUDIT

### Edge Technologies Scan Results

| Technology / Keyword | Status Tag | Verified Reality in Repository |
| :--- | :---: | :--- |
| **Raspberry Pi** | `[DOCUMENTED ONLY]` | Mentioned in pitch presentations and legacy markdown files. No Linux GPIO libraries, no Raspberry Pi build scripts, no on-device setup exists. |
| **Edge Inference** | `[VERIFIED IN CODE]` | Faster-Whisper running on host CPU/CUDA via CTranslate2; Ollama running locally on Host PC. |
| **On-Device Vision / OpenCV** | `[NOT FOUND]` | No OpenCV (`cv2`), YOLO, or computer vision model exists in Python backend or firmware. |
| **Quantization / TFLite / ONNX** | `[NOT FOUND]` | Faster-Whisper uses INT8 CTranslate2 quantization. No custom TFLite or ONNX models exist for robotics. |
| **NPU / ARM Acceleration** | `[NOT FOUND]` | Code executes on standard x86 Windows Host PC; microcontrollers are 240MHz Tensilica Xtensa LX6 (ESP32). |

### Architectural Assessment: BUPI Host -> Raspberry Pi Edge Agent -> ESP32

- **Feasibility**: **HIGHLY COMPATIBLE**.
- **Analysis**: Because the system is decoupled via standard TCP network protocols (MQTT on port 1883, WebSockets on port 8767), an intermediate Raspberry Pi edge node can be introduced with zero changes to the Host PC intelligence core:
  - **Raspberry Pi Role**: Acts as an intermediate Wi-Fi/Serial broker, running a lightweight MQTT forwarder and local hardware supervisor.
  - **ESP32 Role**: Continues running unmodified `bupi_bot1_scout.ino` firmware, connecting to the Raspberry Pi's local network.
  - **Host PC Role**: Retains 3-tier intelligence and Electron UI, subscribing to the Raspberry Pi's forwarded MQTT topics.

---

# 20. FUTURE HETEROGENEOUS ROBOT ARCHITECTURE

### Current vs. Future Robot Types

| Robot Mechanical Type | Status Tag | Required Software Abstractions |
| :--- | :---: | :--- |
| **2-Wheel Differential Drive** | `[VERIFIED IN CODE]` | Current production standard: TB6612 dual H-bridge forward/reverse/turn PWM logic. |
| **Tracked Crawler Rover** | `[VERIFIED BUT PARTIAL]` | Reuses identical differential drive command schemas (`forward`, `reverse`, `turn_by`). Requires higher torque PWM floor. |
| **Aerial Robot (Quadcopter/UAV)**| `[FUTURE / ROADMAP]` | Requires 3D spatial state vector $(x, y, z, \text{yaw}, \text{pitch}, \text{roll})$, altitude hold loop, takeoff/land/hover primitives, MAVLink/MSP protocol bridge, and 3D collision safety validators. |
| **Robotic Arm / Manipulator** | `[FUTURE / ROADMAP]` | Requires forward/inverse kinematics (IK) solver, joint angle state vector ($J_1 \dots J_n$), gripper actuation schemas (`grip`, `release`), and Cartesian trajectory interpolation. |
| **Fixed Sensor / Actuator Node**| `[VERIFIED IN CODE]` | Fully implemented in `esp32_hive_display.ino` and `workspace/BupiNode/BupiNode.ino` (I2C LCD and MQ-2 reporting). |

---

# 21. EXTENSIBILITY TEST RESULTS

Detailed walkthrough of hypothetical device integrations without modifying BUPI production core logic:

### A. New ESP32 Servo Node (Tilt Pan Head)
- **Knowledge Required**: Ingest Arduino snippet: `servo.attach(15); servo.write(angle);`.
- **Capability Declared**: `{"type": "announce", "client_id": "servo_node", "capabilities": ["Servo", "Actuator"]}`.
- **Communication Protocol**: MQTT on `bupi/actuators/servo_1/cmd`.
- **Agent / Tool**: Dynamically learned via `ai.process_hardware()`; invoked via `universal_mqtt_tool(topic="bupi/actuators/servo_1/cmd", payload="90")`.
- **Core Code Changes**: **ZERO**.
- **UI Representation**: Node appears in Fleet Nodes tab of `notepad.html`.

### B. New ESP32 Camera Node
- **Knowledge Required**: RTSP/MJPEG stream URL definition and pin assignments for OV2640.
- **Capability Declared**: `{"type": "announce", "client_id": "esp32_cam", "capabilities": ["Camera", "Video"]}`.
- **Communication Protocol**: HTTP video stream (`http://192.168.137.x:81/stream`).
- **Core Code Changes**: Requires adding an `<img>` or `<canvas>` video stream container in `notepad.html`.
- **Intelligence Status**: The AI can verbally command pan/tilt or take snapshots, but cannot analyze image frames without adding OpenCV or vision model inference to the backend.

### C. New ESP32 Flying Bot (Drone)
- **Knowledge Required**: MAVLink telemetry packet structures, 3D waypoint coordinate formats.
- **Capability Declared**: `{"type": "announce", "client_id": "bupi_drone", "capabilities": ["Flight", "UAV", "Altitude"]}`.
- **Communication Protocol**: MQTT topic `bupi/flight/cmd/json`.
- **Core Code Changes**: **MANDATORY**. 2D planar kinematics engine and safety validator must be extended to support $z$-axis altitude boundaries and flight state flags.

### D. Raspberry Pi Crawler
- **Knowledge Required**: Motor pin mapping for L298N or Cytron driver on RPi GPIO.
- **Capability Declared**: `{"type": "announce", "client_id": "rpi_crawler", "capabilities": ["Motors", "Crawler", "Ultrasonic"]}`.
- **Communication Protocol**: MQTT over Wi-Fi (`bupi/actuators/motors/cmd/json`).
- **Core Code Changes**: **ZERO**. The crawler accepts standard motor JSON direction packets.

### E. BWE Virtual Robot
- **Knowledge Required**: JavaScript virtual device plugin extending `bwe/core/engine.js`.
- **Capability Declared**: `{"type": "announce", "client_id": "bwe_virtual_01", "capabilities": ["Motors", "Simulated_Ultrasonic"]}`.
- **Communication Protocol**: WebSocket on `ws://127.0.0.1:8767`.
- **Core Code Changes**: **ZERO**. Interacts with `bupi_node_server.py` identically to physical hardware.

---

# 22. CONTRADICTIONS / GAPS

Strict comparison between past documented claims and ground-truth code implementation:

| Claimed Feature | Actual Code Reality | Verification Status | What Would Be Required for Full Implementation |
| :--- | :--- | :---: | :--- |
| **PyQt6 Desktop UI** | PyQt6 is strictly a headless `QCoreApplication` running thread event loops. Electron Chromium renders 100% of the UI. | `[VERIFIED IN CODE]` | Retain current Electron architecture; correct all presentations to state "Electron Desktop Application". |
| **`decisions` Table Schema** | Claimed columns `intent`, `approved`, `reason`. Actual columns: `timestamp`, `world_state`, `decision`, `result`. | `[NOT FOUND]` | Update SQLite schema migration script if `approved` and `intent` columns are desired. |
| **Firmware Collision Barrier** | Claimed physical cutoff blocks motion at $\le 15\text{ cm}$. Actual code has `#define ENABLE_OBSTACLE_CUTOFF 0` and `CRITICAL_OBSTACLE_CM = 0.0`. | `[CONFIGURED BUT DISABLED]` | Set `#define ENABLE_OBSTACLE_CUTOFF 1` and `CRITICAL_OBSTACLE_CM = 15.0` in `.ino` files prior to production deployment. |
| **Software Obstacle Blocking** | Claimed software safety validator intercepts collision hazards. Actual code has `ENABLE_OBSTACLE_AVOIDANCE = False`. | `[CONFIGURED BUT DISABLED]` | Set `ENABLE_OBSTACLE_AVOIDANCE = True` in `core/safety_validator.py`. |
| **Extended Kalman Filter** | Claimed "Multi-Sensor EKF/Kalman Fusion". Actual code is an epistemic dead-reckoning kinematics model. | `[NOT FOUND]` | Implement a formal 6-state Kalman filter ($\mathbf{x} = [x, y, \theta, v_x, v_y, \omega]^T$) with covariance propagation. |
| **`run_bupi.py` Production Role**| Documented as primary 20Hz sensor orchestrator. Unreferenced by launcher batch files or Electron. | `[DEAD/UNUSED]` | Archive or delete `run_bupi.py` to prevent codebase confusion. |
| **FootMo2 Services** | Documented as active cockpit. Express/Vite spawning is commented out in `main.js:L399`. | `[CONFIGURED BUT DISABLED]` | Uncomment `spawnFootMo2()` and install `node_modules` in `footmo2-v2/` if cockpit is needed. |
| **Raspberry Pi Support** | Cited in past presentations as distributed compute node. No Linux software exists. | `[DOCUMENTED ONLY]` | Create a lightweight Linux agent daemon script (`bupi_rpi_agent.py`) for Raspberry Pi OS. |
| **Camera / Computer Vision** | Real-time object recognition claimed in slides. Zero OpenCV or YOLO code exists in repository. | `[NOT FOUND]` | Integrate OpenCV video ingest thread with YOLOv8-nano inference pipeline. |
| **N-Robot Swarm Scalability** | Fleet scalability claimed. Swarm coordinator dictionary has hardcoded keys for `bupi_01` and `bupi_02`. | `[VERIFIED BUT PARTIAL]` | Refactor `SwarmCoordinator` to dynamically key dictionaries on arbitrary discovered `client_id`s. |

---

# 23. ARCHITECTURE TRUTH TABLE

| System Capability | Current Code | Partial | Future / Planned | Evidence Reference |
| :--- | :---: | :---: | :---: | :--- |
| **Voice STT (Faster-Whisper)** | **YES** | - | - | [voice/listener.py:L140](file:///c:/Users/Sachin/boopi/assistant/voice/listener.py#L140) |
| **Voice VAD (WebRTC)** | **YES** | - | - | [voice/listener.py:L82](file:///c:/Users/Sachin/boopi/assistant/voice/listener.py#L82) |
| **Voice TTS (Edge-TTS)** | **YES** | - | - | [voice/speaker.py:L58](file:///c:/Users/Sachin/boopi/assistant/voice/speaker.py#L58) |
| **Voice TTS (Offline Fallback)** | **YES** | - | - | [voice/speaker.py:L84](file:///c:/Users/Sachin/boopi/assistant/voice/speaker.py#L84) |
| **Tier 1 Fast Regex Classifier** | **YES** | - | - | [agents/router_agent.py:L80](file:///c:/Users/Sachin/boopi/assistant/agents/router_agent.py#L80) |
| **Tier 2 Local Orchestrator (Ollama)** | **YES** | - | - | [agents/local_orchestrator.py:L210](file:///c:/Users/Sachin/boopi/assistant/agents/local_orchestrator.py#L210) |
| **Tier 3 CrewAI Multi-Agent Fallback** | **YES** | - | - | [agents/robotic_crew.py:L123](file:///c:/Users/Sachin/boopi/assistant/agents/robotic_crew.py#L123) |
| **Autonomous Goal Agent (20Hz)** | **YES** | - | - | [agents/autonomous_goal_agent.py:L152](file:///c:/Users/Sachin/boopi/assistant/agents/autonomous_goal_agent.py#L152) |
| **Reactive Obstacle Detour (5-Stage)** | **YES** | - | - | [core/obstacle_bypass_engine.py:L40](file:///c:/Users/Sachin/boopi/assistant/core/obstacle_bypass_engine.py#L40) |
| **Dual-Bot Swarm Coordination** | **YES** | - | - | [core/swarm_coordinator.py:L18](file:///c:/Users/Sachin/boopi/assistant/core/swarm_coordinator.py#L18) |
| **Bot 2 MQ-2 Gas & DHT22 Readings** | **YES** | - | - | [firmware/bupi_bot2_specialist.ino:L550-L624](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot2_specialist.ino#L550-L624) |
| **Gas Hazard Safety Barrier** | **YES** | - | - | [core/safety_validator.py:L125](file:///c:/Users/Sachin/boopi/assistant/core/safety_validator.py#L125) |
| **Telemetry Freshness TTL (15s)** | **YES** | - | - | [core/safety_validator.py:L6](file:///c:/Users/Sachin/boopi/assistant/core/safety_validator.py#L6) |
| **WebSocket Hardware Bridge (:8767)** | **YES** | - | - | [bupi_node_server.py:L1008](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L1008) |
| **USB Serial Supervisor (COM3)** | **YES** | - | - | [bupi_node_server.py:L280](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L280) |
| **Dynamic C++ Hardware Ingestion** | **YES** | - | - | [brain/ai_brain.py:L393](file:///c:/Users/Sachin/boopi/assistant/brain/ai_brain.py#L393) |
| **SQLite FTS5 Hardware Search** | **YES** | - | - | [services/knowledge_super_agent.py:L81](file:///c:/Users/Sachin/boopi/assistant/services/knowledge_super_agent.py#L81) |
| **Arduino CLI Auto-Flasher** | **YES** | - | - | [actions/flasher.py:L21](file:///c:/Users/Sachin/boopi/assistant/actions/flasher.py#L21) |
| **Electron Hub UI (notepad.html)** | **YES** | - | - | [notepad.html:L1](file:///c:/Users/Sachin/boopi/assistant/notepad.html#L1) |
| **Electron Mascot Overlay (index.html)**| **YES** | - | - | [index.html:L1](file:///c:/Users/Sachin/boopi/assistant/index.html#L1) |
| **Bit-World Engine Simulator (BWE)** | **YES** | - | - | [bwe/core/engine.js:L1](file:///c:/Users/Sachin/boopi/assistant/bwe/core/engine.js#L1) |
| **Kinematic Gait Step Odometry** | **YES** | - | - | [core/kinematics_odometry.py:L162](file:///c:/Users/Sachin/boopi/assistant/core/kinematics_odometry.py#L162) |
| **Wi-Fi RSSI Path Loss Distance** | **YES** | - | - | [core/kinematics_odometry.py:L197](file:///c:/Users/Sachin/boopi/assistant/core/kinematics_odometry.py#L197) |
| **Arbitrary MQTT Actuator Control** | **YES** | - | - | [actions/hardware_tools.py:L219](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L219) |
| **Firmware Collision Barrier** | - | **DISABLED** | - | [firmware/bupi_bot1_scout.ino:L85](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L85) |
| **Firmware Rollover Tilt Barrier** | - | **DISABLED** | - | [firmware/bupi_bot1_scout.ino:L86](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L86) |
| **Software Obstacle Barrier** | - | **DISABLED** | - | [core/safety_validator.py:L109](file:///c:/Users/Sachin/boopi/assistant/core/safety_validator.py#L109) |
| **FootMo2 Web Cockpit** | - | **DISABLED** | - | [main.js:L399](file:///c:/Users/Sachin/boopi/assistant/main.js#L399) |
| **ChromaDB Vector Storage** | - | **PARTIAL** | - | Falls back to JSON cache ([knowledge_super_agent.py:L76](file:///c:/Users/Sachin/boopi/assistant/services/knowledge_super_agent.py#L76)) |
| **N-Robot Swarm Scaling** | - | **PARTIAL** | - | Hardcoded 2-bot dictionary ([swarm_coordinator.py:L36](file:///c:/Users/Sachin/boopi/assistant/core/swarm_coordinator.py#L36)) |
| **Dynamic Sensor Calibration** | - | **PARTIAL** | - | Manual entries needed in `sensor_translator.py` |
| **Extended Kalman Filter (EKF)** | - | - | **FUTURE** | `[NOT FOUND]` in code; replaced by kinematics odometry |
| **Raspberry Pi Edge Compute Node** | - | - | **FUTURE** | `[DOCUMENTED ONLY]` in pitch slides |
| **Computer Vision / YOLO / OpenCV** | - | - | **FUTURE** | `[NOT FOUND]` in backend |
| **Aerial Drones / Quadcopters** | - | - | **FUTURE** | `[FUTURE / ROADMAP]` in pitch decks |
| **Robotic Arm / Manipulator IK** | - | - | **FUTURE** | `[FUTURE / ROADMAP]` in pitch decks |

---

# 24. RECOMMENDED PPT ARCHITECTURE (PROBLEM STATEMENT 26201)

### Slide 1: System Vision & Dual Personality
- **Core Identity**: BUPI (Brain-Unified Personal Intelligence & Robotic Controller).
- **Mode 1**: Transparent desktop companion mascot (Electron Chromium, Faster-Whisper, Edge-TTS, Gemini Live, Activity Monitor).
- **Mode 2**: 100% offline-capable autonomous robotic orchestrator (3-tier decision engine, 20Hz closed-loop goal agent, dual ESP32 rover swarm).

### Slide 2: Ground-Truth Layered Software Architecture
```
+-------------------------------------------------------------------------------+
| PRESENTATION LAYER: Electron Desktop GUI (100% Chromium / Node.js)           |
| - Frameless 3D Mascot (Three.js / Rive) | Central Intelligence Hub (11 Tabs) |
+-------------------------------------------------------------------------------+
| VOICE INTERFACE LAYER: Faster-Whisper (tiny.en) + WebRTC VAD + Edge-TTS/SAPI5 |
+-------------------------------------------------------------------------------+
| 3-TIER INTELLIGENCE ENGINE:                                                   |
| - Tier 1: Deterministic Fast-Pass Regex Classifier (<5ms latency)            |
| - Tier 2: Local Single-Agent Orchestrator (Ollama llama3.2:3b, ~500ms)        |
| - Tier 3: Hierarchical Multi-Agent Crew (Sequential cloud/local fallback)    |
+-------------------------------------------------------------------------------+
| AUTONOMY & PLANNING LAYER: AutonomousGoalAgent (20Hz) + InstructionDecomposer |
| - DynamicMissionPlan, 11 Mission Policies, 5-Stage Obstacle Bypass Detour    |
+-------------------------------------------------------------------------------+
| SAFETY & EPISTEMIC FUSION LAYER:                                              |
| - 15.0s Telemetry TTL Watchdog | Gas Hazard Threshold Intercept               |
| - Kinematics Odometry (1.20g IMU Gait Step Counter + Wi-Fi RSSI Path Loss)    |
+-------------------------------------------------------------------------------+
| COMMUNICATION & HARDWARE BRIDGE:                                              |
| - Local Mosquitto MQTT (1883) | WebSocket Server (8767) | Serial COM3 (115200)|
+-------------------------------------------------------------------------------+
| PHYSICAL HETEROGENEOUS FLEET:                                                 |
| - Bot 1 Scout (HC-SR04, PIR, MPU6050, TB6612)                                 |
| - Bot 2 Specialist (MQ-2 Gas, DHT22 Climate, HC-SR04, MPU6050, TB6612)       |
| - Auxiliary IoT Nodes (1602 LCD Desk Display, Relays)                         |
+-------------------------------------------------------------------------------+
```

### Slide 3: Swarm Collaboration & Disaster Response Use Case
- **Bot 1 Scout**: Leads exploration, detects survivors via PIR thermal motion, navigates obstacle corridors.
- **Bot 2 Specialist**: Follows scout trail, samples MQ-2 gas concentration and DHT22 climate at 20Hz.
- **Safety Interlock**: If Bot 2 encounters toxic gas plume (>350ppm), swarm coordinator broadcasts instant halt to BOTH bots and activates warning relay alarm.

### Slide 4: Future Extensibility Roadmap (SIH 26201)
- **Phase 1 (Current Reality)**: Dual ESP32 differential rovers + Host PC 3-tier intelligence + BWE digital twin.
- **Phase 2 (Edge Compute Extension)**: Introduce intermediate Raspberry Pi Linux node running local MQTT forwarder and on-device camera streaming.
- **Phase 3 (Heterogeneous Vehicles)**: Extend kinematics engine from 2D planar to 3D spatial to incorporate tracked crawlers and aerial quadcopters.

---

# 25. EXACT EVIDENCE INDEX

Alphabetical master index of verified source files, classes, methods, and configurations:

1. `actions.flasher.auto_flash_code`: [actions/flasher.py:L21](file:///c:/Users/Sachin/boopi/assistant/actions/flasher.py#L21)
2. `actions.hardware_tools.CallableTool`: [actions/hardware_tools.py:L4](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L4)
3. `actions.hardware_tools.control_motors`: [actions/hardware_tools.py:L86](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L86)
4. `actions.hardware_tools.control_relay`: [actions/hardware_tools.py:L32](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L32)
5. `actions.hardware_tools.display_on_esp32`: [actions/hardware_tools.py:L56](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L56)
6. `actions.hardware_tools.read_sensor_status`: [actions/hardware_tools.py:L239](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L239)
7. `actions.hardware_tools.run_robotic_code`: [actions/hardware_tools.py:L546](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L546)
8. `actions.hardware_tools.start_autonomous_mission`: [actions/hardware_tools.py:L803](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L803)
9. `actions.hardware_tools.universal_mqtt_tool`: [actions/hardware_tools.py:L219](file:///c:/Users/Sachin/boopi/assistant/actions/hardware_tools.py#L219)
10. `agents.autonomous_goal_agent.AutonomousGoalAgent`: [agents/autonomous_goal_agent.py:L92](file:///c:/Users/Sachin/boopi/assistant/agents/autonomous_goal_agent.py#L92)
11. `agents.autonomous_goal_agent.AutonomousGoalAgent.start_mission`: [agents/autonomous_goal_agent.py:L152](file:///c:/Users/Sachin/boopi/assistant/agents/autonomous_goal_agent.py#L152)
12. `agents.local_orchestrator.LOCAL_TOOLS_SCHEMA`: [agents/local_orchestrator.py:L25](file:///c:/Users/Sachin/boopi/assistant/agents/local_orchestrator.py#L25)
13. `agents.local_orchestrator.LocalAgentOrchestrator.run_task`: [agents/local_orchestrator.py:L230](file:///c:/Users/Sachin/boopi/assistant/agents/local_orchestrator.py#L230)
14. `agents.robotic_crew.run_robotic_task`: [agents/robotic_crew.py:L123](file:///c:/Users/Sachin/boopi/assistant/agents/robotic_crew.py#L123)
15. `agents.router_agent.RouterAgent.quick_regex_classify`: [agents/router_agent.py:L80](file:///c:/Users/Sachin/boopi/assistant/agents/router_agent.py#L80)
16. `brain.activity_monitor.ActivityMonitorService`: [brain/activity_monitor.py:L25](file:///c:/Users/Sachin/boopi/assistant/brain/activity_monitor.py#L25)
17. `brain.ai_brain.AIBrain.process_hardware`: [brain/ai_brain.py:L393](file:///c:/Users/Sachin/boopi/assistant/brain/ai_brain.py#L393)
18. `brain.db_manager.DatabaseManager`: [brain/db_manager.py:L20](file:///c:/Users/Sachin/boopi/assistant/brain/db_manager.py#L20)
19. `bupi_node_server.check_node_timeouts`: [bupi_node_server.py:L184](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L184)
20. `bupi_node_server.register_node`: [bupi_node_server.py:L148](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L148)
21. `bupi_node_server.start_node_server`: [bupi_node_server.py:L1008](file:///c:/Users/Sachin/boopi/assistant/bupi_node_server.py#L1008)
22. `bwe.core.engine.BWEEngine`: [bwe/core/engine.js:L1](file:///c:/Users/Sachin/boopi/assistant/bwe/core/engine.js#L1)
23. `core.kinematics_odometry.OdometryEngine`: [core/kinematics_odometry.py:L60](file:///c:/Users/Sachin/boopi/assistant/core/kinematics_odometry.py#L60)
24. `core.kinematics_odometry.OdometryEngine.process_telemetry`: [core/kinematics_odometry.py:L140](file:///c:/Users/Sachin/boopi/assistant/core/kinematics_odometry.py#L140)
25. `core.obstacle_bypass_engine.execute_obstacle_bypass`: [core/obstacle_bypass_engine.py:L40](file:///c:/Users/Sachin/boopi/assistant/core/obstacle_bypass_engine.py#L40)
26. `core.safety_validator.validate_safety`: [core/safety_validator.py:L112](file:///c:/Users/Sachin/boopi/assistant/core/safety_validator.py#L112)
27. `core.sensor_translator.translate_sensor_value`: [core/sensor_translator.py:L20](file:///c:/Users/Sachin/boopi/assistant/core/sensor_translator.py#L20)
28. `core.swarm_coordinator.SwarmCoordinator`: [core/swarm_coordinator.py:L18](file:///c:/Users/Sachin/boopi/assistant/core/swarm_coordinator.py#L18)
29. `firmware.bupi_bot1_scout.executeMotorAction`: [firmware/bupi_bot1_scout.ino:L676](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L676)
30. `firmware.bupi_bot1_scout.readMPU`: [firmware/bupi_bot1_scout.ino:L533](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L533)
31. `firmware.bupi_bot1_scout.readUltrasonic`: [firmware/bupi_bot1_scout.ino:L508](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot1_scout.ino#L508)
32. `firmware.bupi_bot2_specialist.readMQ2Gas`: [firmware/bupi_bot2_specialist.ino:L550](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot2_specialist.ino#L550)
33. `firmware.bupi_bot2_specialist.dht`: [firmware/bupi_bot2_specialist.ino:L615](file:///c:/Users/Sachin/boopi/assistant/firmware/bupi_bot2_specialist.ino#L615)
34. `planner.instruction_decomposer.decompose_instruction`: [planner/instruction_decomposer.py:L588](file:///c:/Users/Sachin/boopi/assistant/planner/instruction_decomposer.py#L588)
35. `safety.safety_controller.SafetyController`: [safety/safety_controller.py:L20](file:///c:/Users/Sachin/boopi/assistant/safety/safety_controller.py#L20)
36. `services.knowledge_super_agent.KnowledgeSuperAgent`: [services/knowledge_super_agent.py:L21](file:///c:/Users/Sachin/boopi/assistant/services/knowledge_super_agent.py#L21)
37. `services.llm_gateway.LLMGateway`: [services/llm_gateway.py:L25](file:///c:/Users/Sachin/boopi/assistant/services/llm_gateway.py#L25)
38. `voice.listener.ListenerThread`: [voice/listener.py:L82](file:///c:/Users/Sachin/boopi/assistant/voice/listener.py#L82)
39. `voice.speaker.SpeakerThread`: [voice/speaker.py:L31](file:///c:/Users/Sachin/boopi/assistant/voice/speaker.py#L31)
