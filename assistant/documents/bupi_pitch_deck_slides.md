# BUPI Technical Pitch Deck: Verified Slide Architecture & Content

**Project**: BUPI – Agentic AI for Intelligent Physical Interaction  
**Theme**: Robotics & Drones / Physical AI / Disaster Response (SIH 2026 / SIH26218)  
**Core Vision**: **ONE INTELLIGENCE LAYER → MANY ROBOT TYPES**  
**Audit Reference**: [BUPI_MASTER_TECHNICAL_POP_AUDIT.md](../BUPI_MASTER_TECHNICAL_POP_AUDIT.md)

---

## Slide 1: System Architecture Flow (8 Stages)

### Visual Architecture Flow
```
[01. Multi-Modal Input] ──> [02. Hierarchical Router] ──> [03. Mission Decomposer] ──> [04. Swarm Allocator]
                                                                                               │
[08. Physical Fleet]   <── [07. Unified Bridge]    <── [06. Safety Supervisor] <── [05. 20Hz Telemetry]
         │                                                                                    ▲
         └─────────────────────── Real-Time 20 Hz Closed-Loop Telemetry ──────────────────────┘
```

### Stage Details (Code-Verified)
1. **01. Multi-Modal Input**: Voice input via Faster-Whisper local STT, text commands, and Mission Studio UI.
2. **02. Hierarchical Intent Router**:
   - **Tier 1 Fast-Pass (<5ms)**: Regex lexical tokenizer for immediate E-stops, motor drives, and compiled missions.
   - **Tier 2 Local LLM (~500ms)**: Ollama `llama3.2:3b` executing 12 hardware tool schemas offline.
   - **Tier 3 CrewAI Fallback (5–15s)**: Multi-agent hierarchical delegation for complex problem solving.
3. **03. Mission Decomposer**: Compiles natural language into `DynamicMissionPlan` objects using `PolicyType` enums (`SCAN_SWEEP`, `APPROACH_TARGET`, `CONDITIONAL_MOVE`, `EXPLORE_SAFE`, `SWARM_COOPERATIVE`) with dynamic sensory exit criteria.
4. **04. Swarm & Capability Allocator**: Discovers live hardware nodes via WebSocket/MQTT handshakes, auto-routing tasks by sensor capability (Bot 1 for thermal search, Bot 2 for gas/climate).
5. **05. Multi-Sensor Decision Fusion**: Real-time 20 Hz (50ms) telemetry stream: HC-SR04 ultrasonic range, MPU-6050 6-axis IMU odometry, PIR motion, MQ-2 gas, and DHT22 climate data.
6. **06. Deterministic Safety Supervisor**: Unconditional hardware overrides: Voice E-Stop (<5ms), ultrasonic proximity barrier ($\le 15$ cm), rollover tilt lock ($>35^\circ$), and 15s telemetry TTL watchdog.
7. **07. Unified Hardware Bridge**: Asynchronous WebSockets (`ws://192.168.137.1:8767` @ 20 Hz), Mosquitto MQTT (`:1883`), and USB Serial (`COM3` @ 115200 baud).
8. **08. Physical Ground Fleet**: Dual ESP32 differential rovers:
   - **Bot 1 (Scout)**: TB6612FNG + N20 motors + HC-SR04 + MPU6050 + PIR thermal motion sensor.
   - **Bot 2 (Specialist)**: TB6612FNG + N20 motors + HC-SR04 + MPU6050 + MQ-2 gas/smoke + DHT22 climate sensor.

---

## Slide 2: Proposed Solution: BUPI Architecture

### Slide Content (Copy-Paste Ready for PPT / Canva)

#### **Title:** Proposed Solution: BUPI
**Subtitle:** *Agentic AI for Multi-Robot Physical Interaction & Autonomous Exploration*  
**Core Thesis:** *One Intelligence Layer → Many Robot Types*

#### Card 1: Goal-Driven Interaction
- Translates natural language voice and text into structured mission plans (`DynamicMissionPlan`).
- Replaces manual teleoperation with autonomous policy execution (`SCAN_SWEEP`, `APPROACH_TARGET`, `EXPLORE_SAFE`).
- Evaluates dynamic stopping conditions in real time (ultrasonic distance, PIR motion, gas PPM).

#### Card 2: Capability-Aware Planning
- Automatically discovers connected hardware nodes via WebSocket & MQTT announcements.
- Matches tasks to onboard sensors without hardcoded routines.
- Routes thermal search to **Bot 1 (Scout)** and gas/climate monitoring to **Bot 2 (Specialist)**.

#### Card 3: Autonomous Physical Execution
- Runs a local **20 Hz (50ms)** closed-loop Observe-Reason-Act cycle.
- Tracks position using MPU-6050 gait step counting and gyro dead reckoning.
- Features an autonomous 5-step detour maneuver to flank obstacles without cloud latency.

#### Card 4: Safety-First Operation
- Sub-5ms voice emergency stop (`stop`, `halt`, `e-stop`) immediately cuts motor channels.
- Hard proximity barrier ($\le 15\text{ cm}$) and chassis tilt limit ($>35^\circ$) override planner commands.
- 15-second telemetry freshness watchdog halts movement if wireless communication drops.

#### Operational Highlight: 100% Offline Edge Autonomy
- Operates completely air-gapped without internet access using local Faster-Whisper, local Ollama `llama3.2:3b`, SAPI5 TTS, and local WebSockets/MQTT on host laptop hotspot.

---

## Technical Defense: Prohibited Claims Checklist

To protect technical credibility during hackathon evaluation, adhere strictly to codebase reality:

| What to Claim (Verified) | What NOT to Claim (Prohibited) | Why |
| :--- | :--- | :--- |
| **Inertial Dead Reckoning & Ultrasonic Clearance** | ❌ **LiDAR or Camera SLAM** | No LiDAR or camera hardware is present; odometry uses MPU6050 gait steps + gyro yaw + RF path loss. |
| **Epistemic Decision & State Fusion** | ❌ **Extended Kalman Filter (EKF)** | Code uses peak dynamic acceleration debouncing and threshold fusion, not covariance matrices. |
| **Deterministic State Machine Locomotion** | ❌ **Reinforcement Learning** | Control loops and 5-step detour maneuvers are deterministic finite state machines. |
| **Differential Ground Rover Fleet (Bot 1 + Bot 2)** | ❌ **Autonomous Drone Flights** | Drone action schemas exist in JSON capability templates, but aerial hardware is not physically integrated. |
