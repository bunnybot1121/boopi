# BUPI MASTER SYSTEM ARCHITECTURE DIAGRAMS (PROBLEM STATEMENT 26201)
## Verified Architectural Diagrams & Process Models

> **Document Type**: Technical Architecture Diagram Specifications  
> **Source Ground Truth**: Verified against production code in `c:\Users\Sachin\boopi\assistant`  
> **Target Problem Statement**: SIH Problem Statement 26201

---

## 1. Production Process & Thread Tree Diagram

```mermaid
graph TD
    subgraph Host_OS [Windows 11 Host Operating System]
        BAT["Run_Bupi_Robot.bat<br/>(Master Launcher Script)"]
        
        subgraph Daemons [Background Services & Servers]
            MOSQ["mosquitto.exe<br/>Port: 127.0.0.1:1883 (TCP Broker)"]
            OLLAMA["ollama.exe serve<br/>Port: 127.0.0.1:11434 (HTTP REST)"]
            HOTSPOT["powershell.exe ensure_hotspot.ps1<br/>Gateway: 192.168.137.1 (2.4GHz Wi-Fi)"]
        end
        
        subgraph Electron_Runtime [Electron 41.2.1 Desktop Runtime]
            MAIN_JS["electron.exe main.js<br/>(Main Orchestration Process)"]
            RENDER_MASCOT["Renderer: index.html<br/>(250x250 Frameless 3D Mascot)"]
            RENDER_HUB["Renderer: notepad.html<br/>(1200x800 Central Control Hub - 11 Tabs)"]
        end
        
        subgraph Python_Mode1 [Python Mode 1 Supervisor: main.py]
            QT_CORE["MainThread: QCoreApplication Event Loop"]
            STT_TH["ListenerThread (QThread)<br/>sounddevice + webrtcvad + Faster-Whisper"]
            TTS_TH["SpeakerThread (QThread)<br/>Edge-TTS / SAPI5 pyttsx3 fallback"]
            AI_TH["AIThread (QThread)<br/>Mode 1 Companion LLM Streaming"]
            ACT_TH["ActivityMonitorService (Thread)<br/>Idle time & active window titles"]
            WS_TH["WebSocketServer (Thread)<br/>asyncio serve on 0.0.0.0:8767"]
            SER_TH["SerialSupervisor (Thread)<br/>USB COM3 at 115200 baud"]
            DB_TH["DbWriter (Thread)<br/>1.5s telemetry batch writer to bupi_telemetry.db"]
            STDIN_TH["StdinReader (Thread)<br/>Listens to JSON commands from Electron"]
        end
        
        subgraph Python_Mode2 [Python Mode 2 Robotic Worker: run_mode2.py]
            M2_MAIN["MainThread: Mode2_Main_Worker Keepalive"]
            M2_MQTT["MQTT Client Network Loop<br/>Subscribes: bupi/internal/utterance"]
            UTT_WORKER["Dynamic Worker Thread<br/>process_with_crew(text)"]
            MISSION_TH["AutonomousGoalAgent Thread<br/>20Hz Closed-Loop Mission Engine"]
        end
    end

    BAT --> MOSQ
    BAT --> OLLAMA
    BAT --> HOTSPOT
    BAT --> MAIN_JS
    
    MAIN_JS --> RENDER_MASCOT
    MAIN_JS --> RENDER_HUB
    MAIN_JS -- "spawnEngine(main.py --mode 2)" --> Python_Mode1
    
    Python_Mode1 -- "start_mode2_process(run_mode2.py)" --> Python_Mode2
    
    MAIN_JS <== "Bidirectional stdin/stdout JSON lines" ==> STDIN_TH
    Python_Mode1 <== "Local Mosquitto MQTT: bupi/internal/*" ==> Python_Mode2
```

---

## 2. 3-Tier Intelligence & Decision Routing Architecture

```mermaid
flowchart TD
    INPUT([User Voice / Text Utterance]) --> ROUTER{Tier 1: RouterAgent<br/>quick_regex_classify}
    
    subgraph Tier1 [Tier 1: Deterministic Microsecond Fast-Pass]
        ROUTER -- "Match: Stop, Halt, Freeze" --> T1_ESTOP[Emergency Stop Command<br/>direct hardware motor halt]
        ROUTER -- "Match: Move Direction, Step, Turn" --> T1_MOVE[Direct Motor Command<br/>hardware_tools.control_motors]
        ROUTER -- "Match: Sensor Status, Read Gas" --> T1_SENS[Direct Telemetry Query<br/>hardware_tools.read_sensor_status]
    end
    
    ROUTER -- "Unmatched / Complex / Ambiguous" --> TIER2{Tier 2: LocalAgentOrchestrator<br/>run_task via Ollama}
    
    subgraph Tier2 [Tier 2: Single-Turn Local Edge LLM]
        TIER2 --> OLLAMA_CALL[Call Ollama /v1/chat/completions<br/>Model: llama3.2:3b / llama3.1:8b]
        OLLAMA_CALL --> TOOL_SCHEMA[12 OpenAI-Compatible Tool Schemas<br/>control_motors, start_autonomous_mission, etc.]
        TOOL_SCHEMA --> TOOL_EXEC[Execute Tool via actions/hardware_tools.py]
    end
    
    TIER2 -- "Ollama Unreachable / Exception / Complex Plan" --> TIER3{Tier 3: RoboticCrew<br/>run_robotic_task via CrewAI}
    
    subgraph Tier3 [Tier 3: Hierarchical Multi-Agent Crew Fallback]
        TIER3 --> SEQ_FALLBACK[Sequential Model Fallback Chain]
        SEQ_FALLBACK --> FB1[1. ollama/llama3.2:3b]
        FB1 -- Error --> FB2[2. ollama/llama3.1:8b]
        FB2 -- Error --> FB3[3. gemini/gemini-2.5-flash]
        FB3 -- Error --> FB4[4. groq/llama-3.3-70b-versatile]
        FB4 -- Error --> FB5[5. nvidia/deepseek-v4-pro]
        FB5 -- Error --> FB6[6. openrouter/meta-llama-3.3-70b:free]
        
        SEQ_FALLBACK --> CREW_AGENTS[CrewAI Multi-Agent Execution<br/>Scout Analyst + Specialist + Coordinator]
    end
    
    T1_ESTOP --> SAFETY_GATE[Safety & TTL Validator Gate]
    T1_MOVE --> SAFETY_GATE
    T1_SENS --> SAFETY_GATE
    TOOL_EXEC --> SAFETY_GATE
    CREW_AGENTS --> SAFETY_GATE
    
    SAFETY_GATE -- "Approved: True" --> DISPATCH[MQTT / WebSocket Hardware Dispatch]
    SAFETY_GATE -- "Approved: False" --> BLOCK[Command Blocked & Reason Logged]
```

---

## 3. Hardware Communication & Network Topology

```mermaid
graph LR
    subgraph Host_PC [Host PC Architecture - 192.168.137.1]
        subgraph Ports [Network & Bus Services]
            P_MQTT["TCP :1883<br/>Mosquitto Broker"]
            P_WS["WebSocket :8767<br/>bupi_node_server.py"]
            P_SER["UART Serial COM3<br/>115200 Baud"]
            P_OLL["HTTP :11434<br/>Ollama REST API"]
        end
        
        DB[("bupi_telemetry.db<br/>SQLite Storage")]
        P_WS --> DB
    end

    subgraph Physical_Swarm [Physical Embedded Fleet: 2.4GHz Hotspot Subnet 192.168.137.0/24]
        subgraph Bot1 [Bot 1: Scout Rover - bupi_01]
            ESP1[ESP32 Dev Module]
            MOT1[TB6612 + Dual N20 Motors]
            US1[HC-SR04 Ultrasonic GPIO 5/18]
            IMU1[MPU6050 6-Axis IMU I2C 0x68]
            PIR1[PIR Motion Sensor GPIO 34/19]
            ESP1 --> MOT1
            ESP1 --> US1
            ESP1 --> IMU1
            ESP1 --> PIR1
        end
        
        subgraph Bot2 [Bot 2: Environmental Specialist - bupi_02]
            ESP2[ESP32 Dev Module]
            MOT2[TB6612 + Dual N20 Motors]
            US2[HC-SR04 Ultrasonic GPIO 5/18]
            IMU2[MPU6050 6-Axis IMU I2C 0x68]
            MQ2[MQ-2 Gas Sensor GPIO 34 ADC]
            DHT[DHT22 Climate Sensor GPIO 4]
            ESP2 --> MOT2
            ESP2 --> US2
            ESP2 --> IMU2
            ESP2 --> MQ2
            ESP2 --> DHT
        end
        
        subgraph DisplayNode [Auxiliary Desk Display - bupi_display]
            ESP3[ESP32 Dev Module]
            LCD[1602 LCD via PCF8574 I2C 0x27]
            ESP3 --> LCD
        end
    end

    ESP1 <== "WebSocket: ws://192.168.137.1:8767<br/>20Hz Telemetry Stream" ==> P_WS
    ESP2 <== "WebSocket: ws://192.168.137.1:8767<br/>20Hz Telemetry Stream" ==> P_WS
    ESP3 <== "WebSocket / MQTT Announcements" ==> P_WS
    
    ESP1 -. "USB Wired Fallback COM3" .-> P_SER
    
    P_MQTT -- "Command: bupi/actuators/motors/cmd/json" --> P_WS
```

---

## 4. 20Hz Closed-Loop Autonomy Cycle (Observe -> Reason -> Act)

```mermaid
stateDiagram-v2
    [*] --> Idle : System Ready

    Idle --> Decomposing : Voice Instruction Received ("Find human and check gas")
    Decomposing --> MissionLoop : DynamicMissionPlan Instantiated (instruction_decomposer.py:588)

    state MissionLoop {
        [*] --> Observe
        
        state "1. OBSERVE (5ms)" as Observe {
            FetchSensors: Query bupi_node_server.py latest telemetry
            ReadUltrasonic: HC-SR04 distance
            ReadIMU: MPU6050 6-axis acceleration and gyro
            ReadEnvironment: MQ-2 Gas PPM, DHT22 Temp/Humidity, PIR
            ComputeOdometry: kinematics_odometry.process_telemetry()
        }
        
        Observe --> Reason
        
        state "2. REASON (10ms)" as Reason {
            CheckStagePolicy: Match current active stage against 11 Policies
            CheckHazards: Gas > 300ppm or Obstacle < 15cm
            CheckStopCondition: Distance met, target acquired, or timeout
        }
        
        Reason --> BypassObstacle : Obstacle < 15cm detected
        Reason --> AbortHazard : Gas > 300ppm detected
        Reason --> StageComplete : Stop Condition Satisfied
        Reason --> Act : Path Clear & Moving
        
        state "3. ACT (5ms)" as Act {
            ComputeVector: Linear speed & heading bias
            PublishMotorCmd: MQTT bupi/actuators/motors/cmd/json
            StreamUIState: Broadcast mission progress to 2D Arena
        }
        
        Act --> Sleep50ms
        Sleep50ms --> Observe : 20Hz Frequency Maintained
    }

    state "Obstacle Bypass Engine" as BypassObstacle {
        Reverse15: Reverse 15cm
        Pivot60: Pivot Right 60 deg
        Advance30: Advance Flank 30cm
        CounterPivot: Counter-Pivot Left -60 deg
        Resume: Resume Path
        Reverse15 --> Pivot60 --> Advance30 --> CounterPivot --> Resume
    }
    
    BypassObstacle --> MissionLoop : Detour Completed
    
    StageComplete --> MissionLoop : Next Stage in DynamicMissionPlan
    StageComplete --> MissionFinished : All Stages Completed
    
    AbortHazard --> EmergencyHalt : Swarm Evacuation Broadcast
    EmergencyHalt --> [*] : Mission Aborted Safely
    MissionFinished --> [*] : Mission Succeeded & Debrief Saved
```

---

## 5. Multi-Layer Safety Interlock & Hazard Cascade

```mermaid
graph TD
    subgraph Trigger [Hazard Detection Sources]
        H_GAS["MQ-2 Gas Sensor: reading > 300 ppm"]
        H_US["HC-SR04 Ultrasonic: distance <= 15.0 cm"]
        H_TILT["MPU6050 IMU: tilt angle > 45.0 degrees"]
        H_TTL["Telemetry Freshness Watchdog: age > 15.0 seconds"]
        H_HB["Node Heartbeat Monitor: silence > 15.0 seconds"]
        H_REG["Voice E-Stop Regex: 'stop', 'halt', 'freeze'"]
    end

    subgraph Intercept_Layers [Safety Intercept & Validation Layers]
        L1["Layer 1: Deterministic Router E-Stop<br/>(agents/router_agent.py:80)"]
        L2["Layer 2: Software Safety Validator<br/>(core/safety_validator.py:112)"]
        L3["Layer 3: Swarm Evacuation Coordinator<br/>(core/swarm_coordinator.py:131)"]
        L4["Layer 4: Hardware Bridge Node Server<br/>(bupi_node_server.py:184)"]
        L5["Layer 5: Microcontroller Firmware Auto-Stop<br/>(firmware/bupi_bot1_scout.ino:676)"]
    end

    subgraph Actions [Enforced Safety Actions]
        ACT_STOP["Instant Hardware Motor Halt<br/>left=0, right=0"]
        ACT_BLOCK["Reject New Movement Commands<br/>approved=False, reason logged"]
        ACT_EVAC["Swarm Evacuation Broadcast<br/>Halt Bot 1 & Bot 2 simultaneously"]
        ACT_OFF["Mark Node State as OFFLINE<br/>bupi_node_server node registry"]
        ACT_ALARM["Trigger Warning Buzzer / Relay<br/>Activate ventilation/alarm"]
    end

    H_REG --> L1 --> ACT_STOP
    H_GAS --> L2 & L3
    H_US --> L2 & L5
    H_TILT --> L2 & L5
    H_TTL --> L2 --> ACT_BLOCK
    H_HB --> L4 --> ACT_OFF
    
    L2 -- "Gas Hazard Detected" --> ACT_BLOCK & ACT_ALARM
    L3 -- "Toxic Gas Plume (>350ppm)" --> ACT_EVAC --> ACT_STOP
    L5 -- "Local duration elapsed (ms)" --> ACT_STOP
```

---

## 6. Dynamic C++ Hardware Ingestion & Self-Learning Pipeline

```mermaid
sequenceDiagram
    autonumber
    actor User as Engineer / Operator
    participant UI as Electron Hub (notepad.html)
    participant Brain as AI Brain (ai_brain.py:393)
    participant KSA as Knowledge Super-Agent (knowledge_super_agent.py)
    participant FTS5 as SQLite FTS5 Hardware Store
    participant Flasher as Auto-Flasher (actions/flasher.py)
    participant HW as Physical ESP32 on COM Port
    participant Tools as Hardware Tools & LLM (hardware_tools.py)

    User->>UI: Pastes raw Arduino C++ snippet for new peripheral (e.g. Servo / Sensor)
    UI->>Brain: Invokes process_hardware(raw_code)
    Brain->>KSA: Requests hardware profile & pinout resolution
    KSA->>FTS5: Executes <1ms FTS5 text search on library definitions & pin rules
    FTS5-->>KSA: Returns matching hardware knowledge card
    KSA-->>Brain: Injects knowledge card into hardware_rules.md prompt
    Brain->>Brain: Synthesizes complete Arduino sketch with WiFi & MQTT handlers
    Brain->>Brain: Appends command syntax rule to hardware_memory.txt
    Brain->>Flasher: Passes synthesized sketch to auto_flash_code()
    Flasher->>Flasher: Compiles sketch via local arduino-cli binary
    Flasher->>HW: Flashes binary over auto-detected USB COM port
    HW-->>Flasher: ESP32 boots and connects to 192.168.137.1 Hotspot
    Flasher-->>UI: Displays compilation & flash success log
    Note over Tools,HW: From this moment on, Tier 2 & Tier 3 LLMs read hardware_memory.txt<br/>and control the new peripheral via universal_mqtt_tool without changing any Python core code!
```

---

## 7. Heterogeneous Swarm Fusion & Sensor Specialization Architecture

```mermaid
graph TD
    subgraph Recon_Scout [Bot 1: Reconnaissance Scout - bupi_01]
        direction TB
        B1_HW[ESP32 + Dual N20 Motors]
        B1_S1[HC-SR04 Ultrasonic Sensor]
        B1_S2[MPU6050 6-Axis IMU]
        B1_S3[PIR Pyroelectric Thermal Motion]
        B1_OUT[20Hz Scout Telemetry Packet:<br/>dist, ax, ay, az, gx, gy, gz, pir, rssi]
        B1_HW --- B1_S1 & B1_S2 & B1_S3 --> B1_OUT
    end

    subgraph Env_Specialist [Bot 2: Environmental Specialist - bupi_02]
        direction TB
        B2_HW[ESP32 + Dual N20 Motors]
        B2_S1[HC-SR04 Ultrasonic Sensor]
        B2_S2[MPU6050 6-Axis IMU]
        B2_S3[MQ-2 Toxic Gas Sensor]
        B2_S4[DHT22 Climate Sensor]
        B2_OUT[20Hz Specialist Telemetry Packet:<br/>dist, gas_ppm, temp_c, hum_pct, ax, ay, az, rssi]
        B2_HW --- B2_S1 & B2_S2 & B2_S3 & B2_S4 --> B2_OUT
    end

    subgraph Central_Fusion [Swarm Coordinator & Epistemic Fusion Engine]
        SWARM_COORD["SwarmCoordinator (core/swarm_coordinator.py)"]
        FUSION_LOGIC["Tandem State Fusion:<br/>- Fused Scout Lead Corridor Profile<br/>- Atmospheric Hazard Layering<br/>- Simultaneous Position Tracking"]
        KIN_ODO["Kinematics Odometry (core/kinematics_odometry.py):<br/>- IMU 1.20g Gait Step Counting<br/>- Gyro Yaw Dead-Reckoning<br/>- Wi-Fi RSSI Path Loss Distance"]
    end

    subgraph Consumers [System Consumers & Tactical Visualizations]
        ARENA["2D Tactical Arena Canvas (spatial_twin_2d.html)"]
        GOAL_AGENT["AutonomousGoalAgent 20Hz Mission Engine"]
        SAFETY_SYS["Safety & Emergency Evacuation Interlock"]
        DB_RECORD["bupi_telemetry.db Database Store"]
    end

    B1_OUT ==> SWARM_COORD
    B2_OUT ==> SWARM_COORD
    
    SWARM_COORD --> FUSION_LOGIC
    SWARM_COORD --> KIN_ODO
    
    FUSION_LOGIC --> ARENA
    FUSION_LOGIC --> GOAL_AGENT
    FUSION_LOGIC --> SAFETY_SYS
    FUSION_LOGIC --> DB_RECORD
```

---
*End of Architecture Diagram Specifications — SIH Problem Statement 26201*
