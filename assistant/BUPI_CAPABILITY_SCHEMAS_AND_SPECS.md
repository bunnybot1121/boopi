# BUPI CAPABILITY SCHEMAS & HARDWARE SPECIFICATIONS (PS 26201)
## Canonical JSON Schemas, Packet Definitions & Device Extensibility Blueprints

> **Document Type**: Hardware Capability Schemas & Extensibility Specifications  
> **Source Ground Truth**: Verified against `bupi_node_server.py`, `firmware/*.ino`, and `actions/hardware_tools.py`  
> **Target Problem Statement**: SIH Problem Statement 26201

---

## 1. Canonical Node Announcement Schema

When any embedded node (physical ESP32, Raspberry Pi, or BWE simulated device) connects to BUPI over WebSockets (`ws://192.168.137.1:8767`) or MQTT (`bupi/nodes/announce`), it registers its operational capabilities with `bupi_node_server.py`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "BupiNodeAnnouncement",
  "type": "object",
  "required": ["type", "client_id", "capabilities"],
  "properties": {
    "type": {
      "type": "string",
      "enum": ["announce", "register", "heartbeat"]
    },
    "client_id": {
      "type": "string",
      "description": "Unique network identifier for the physical node (e.g., bupi_01, bupi_02, esp32_hive)"
    },
    "role": {
      "type": "string",
      "enum": ["scout", "specialist", "display", "crawler", "uav", "sensor_beacon"],
      "description": "High-level operational role within the multi-robot fleet"
    },
    "device_type": {
      "type": "string",
      "description": "Hardware architecture (e.g., ESP32_WROOM_32D, ESP32_S3, Raspberry_Pi_5)"
    },
    "capabilities": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Declared functional capabilities registered into the central node registry",
      "examples": [
        ["Motors", "Ultrasonic", "IMU", "PIR_Motion"],
        ["Motors", "Ultrasonic", "IMU", "MQ2_Gas", "DHT22_Climate"],
        ["LCD_1602", "I2C_Backpack"]
      ]
    },
    "sensors": {
      "type": "object",
      "properties": {
        "ultrasonic": { "type": "boolean" },
        "imu": { "type": "boolean" },
        "pir": { "type": "boolean" },
        "gas": { "type": "boolean" },
        "climate": { "type": "boolean" }
      }
    },
    "actuators": {
      "type": "object",
      "properties": {
        "differential_motors": { "type": "boolean" },
        "servo": { "type": "boolean" },
        "relay": { "type": "boolean" },
        "display": { "type": "boolean" }
      }
    },
    "ip_address": {
      "type": "string",
      "format": "ipv4",
      "description": "Static or DHCP IP assigned by Windows Hotspot (192.168.137.x)"
    },
    "firmware_version": {
      "type": "string",
      "description": "Semantic versioning string of deployed Arduino sketch"
    }
  }
}
```

### Concrete Production Announcement Examples

#### Bot 1: Reconnaissance Scout
```json
{
  "type": "announce",
  "client_id": "bupi_01",
  "role": "scout",
  "device_type": "ESP32_WROOM_32D",
  "capabilities": ["Motors", "Ultrasonic", "IMU", "PIR_Motion"],
  "sensors": { "ultrasonic": true, "imu": true, "pir": true, "gas": false, "climate": false },
  "actuators": { "differential_motors": true, "servo": false, "relay": false, "display": false },
  "ip_address": "192.168.137.101",
  "firmware_version": "bupi_scout_v2.4.1"
}
```

#### Bot 2: Environmental Specialist
```json
{
  "type": "announce",
  "client_id": "bupi_02",
  "role": "specialist",
  "device_type": "ESP32_WROOM_32D",
  "capabilities": ["Motors", "Ultrasonic", "IMU", "MQ2_Gas", "DHT22_Climate"],
  "sensors": { "ultrasonic": true, "imu": true, "pir": false, "gas": true, "climate": true },
  "actuators": { "differential_motors": true, "servo": false, "relay": false, "display": false },
  "ip_address": "192.168.137.102",
  "firmware_version": "bupi_specialist_v2.4.1"
}
```

---

## 2. Canonical 20Hz Live Telemetry Packet Schema

Nodes stream telemetry at **20Hz (50ms interval)** over WebSocket `:8767` or USB Serial UART at 115200 baud:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "BupiTelemetryPacket",
  "type": "object",
  "required": ["node_id", "timestamp"],
  "properties": {
    "node_id": { "type": "string" },
    "timestamp": { "type": "number", "description": "Unix timestamp or uptime millisecond counter" },
    "ultrasonic": {
      "type": "object",
      "properties": {
        "distance_cm": { "type": "number", "minimum": 0.0, "maximum": 400.0 }
      }
    },
    "imu": {
      "type": "object",
      "properties": {
        "ax": { "type": "number" },
        "ay": { "type": "number" },
        "az": { "type": "number" },
        "gx": { "type": "number" },
        "gy": { "type": "number" },
        "gz": { "type": "number" },
        "tilt_deg": { "type": "number" }
      }
    },
    "environmental": {
      "type": "object",
      "properties": {
        "mq2_gas_raw": { "type": "integer", "minimum": 0, "maximum": 4095 },
        "mq2_gas_ppm": { "type": "number" },
        "temperature_c": { "type": "number" },
        "humidity_pct": { "type": "number" },
        "pir_motion_detected": { "type": "boolean" }
      }
    },
    "network": {
      "type": "object",
      "properties": {
        "rssi_dbm": { "type": "integer", "minimum": -100, "maximum": 0 },
        "wifi_connected": { "type": "boolean" }
      }
    },
    "odometry": {
      "type": "object",
      "properties": {
        "total_steps": { "type": "integer" },
        "x_pos_m": { "type": "number" },
        "y_pos_m": { "type": "number" },
        "yaw_deg": { "type": "number" }
      }
    }
  }
}
```

---

## 3. Canonical Actuator Command Schemas

### A. Differential Motor Command Schema
Published to MQTT topic: `bupi/actuators/motors/cmd/json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "BupiMotorCommand",
  "type": "object",
  "required": ["action"],
  "properties": {
    "action": {
      "type": "string",
      "enum": ["forward", "backward", "left", "right", "stop", "custom"]
    },
    "left_speed": {
      "type": "integer",
      "minimum": -255,
      "maximum": 255,
      "description": "PWM speed for left motor channel (TB6612 AIN1/AIN2)"
    },
    "right_speed": {
      "type": "integer",
      "minimum": -255,
      "maximum": 255,
      "description": "PWM speed for right motor channel (TB6612 BIN1/BIN2)"
    },
    "duration_ms": {
      "type": "integer",
      "minimum": 0,
      "maximum": 10000,
      "description": "Auto-stop timeout enforced on microcontroller firmware"
    },
    "target_robot": {
      "type": "string",
      "enum": ["bupi_01", "bupi_02", "all"],
      "default": "bupi_01"
    }
  }
}
```

### B. Universal Dynamic MQTT Actuator Schema
Invoked by `actions/hardware_tools.py:universal_mqtt_tool` for arbitrary new peripherals:

```json
{
  "topic": "bupi/actuators/{device_name}/cmd",
  "payload": "{command_string_or_json}"
}
```

---

## 4. Canonical Dynamic Mission Plan Schema

Generated by `planner/instruction_decomposer.py:L588` and executed by `agents/autonomous_goal_agent.py`:

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DynamicMissionPlan",
  "type": "object",
  "required": ["mission_id", "raw_instruction", "stages"],
  "properties": {
    "mission_id": { "type": "string" },
    "raw_instruction": { "type": "string" },
    "timeout_sec": { "type": "number", "default": 60.0 },
    "stages": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["stage_index", "policy_name", "stop_condition"],
        "properties": {
          "stage_index": { "type": "integer" },
          "policy_name": {
            "type": "string",
            "enum": [
              "EXPLORE_AND_MAP",
              "PATROL_PERIMETER",
              "SURVIVOR_SEARCH",
              "GAS_LEAK_INVESTIGATION",
              "TARGET_APPROACH",
              "RETURN_TO_ORIGIN",
              "OBSTACLE_AVOIDANCE_STAGE",
              "COLLABORATIVE_SWARM_SWEEP",
              "STATIONARY_MONITOR"
            ]
          },
          "target_bot": { "type": "string", "default": "bupi_01" },
          "speed_pwm": { "type": "integer", "default": 180 },
          "stop_condition": {
            "type": "object",
            "required": ["type"],
            "properties": {
              "type": {
                "type": "string",
                "enum": ["distance_met", "pir_triggered", "gas_threshold_exceeded", "timeout", "obstacle_detected"]
              },
              "threshold_value": { "type": "number" }
            }
          }
        }
      }
    }
  }
}
```

---

## 5. Extensibility Test: 4 Hypothetical Device Integrations

### Hypothetical Device A: ESP32 + Servo Tilt-Pan + HC-SR04 Scanner
- **Objective**: Add a pan-tilt sonar radar to scout corridors.
- **Announcement Packet**:
  ```json
  {
    "type": "announce",
    "client_id": "sonar_turret_01",
    "role": "scout",
    "capabilities": ["Servo_Pan", "Ultrasonic_Sweep"],
    "ip_address": "192.168.137.105"
  }
  ```
- **Firmware Ingestion**:
  ```cpp
  #include <ESP32Servo.h>
  Servo panServo;
  void setup() {
    panServo.attach(13);
  }
  void onMqttCommand(char* topic, byte* payload, unsigned int length) {
    int angle = atoi((char*)payload);
    panServo.write(angle);
  }
  ```
- **What Can Be Reused**:
  - `bupi_node_server.py`: Node registration, heartbeat monitoring, and WebSocket bridge.
  - `actions/hardware_tools.py`: `universal_mqtt_tool(topic="bupi/actuators/sonar_turret_01/cmd", payload="90")`.
  - Electron Fleet Nodes Tab: Automatically displays node card.
- **What Must Be Added**:
  - Rule in `hardware_memory.txt`: `- Sonar Turret: To pan head to angle X, send [MQTT_SEND:bupi/actuators/sonar_turret_01/cmd:X]`.
- **Python Core Changes Required**: **ZERO (0) LINES**.

---

### Hypothetical Device B: ESP32-CAM (AI-Thinker OV2640)
- **Objective**: Provide low-latency visual snapshots of survivor locations.
- **Announcement Packet**:
  ```json
  {
    "type": "announce",
    "client_id": "bupi_cam_01",
    "role": "scout",
    "capabilities": ["Camera_Stream", "Snapshot_Capture"],
    "ip_address": "192.168.137.106",
    "stream_url": "http://192.168.137.106:81/stream"
  }
  ```
- **What Can Be Reused**:
  - Hotspot networking infrastructure (`192.168.137.0/24`).
  - Node registration database (`bupi_telemetry.db:nodes`).
- **What Must Be Added**:
  - UI Video Viewport in `notepad.html`: `<img id="camera-stream" src="http://192.168.137.106:81/stream"/>`.
  - Action tool in `actions/hardware_tools.py`: `capture_camera_snapshot()` to download JPEG buffer.
- **Python Core Changes Required**: ~15 lines in `hardware_tools.py` to add snapshot fetch tool. Backend computer vision requires adding OpenCV (`cv2`).

---

### Hypothetical Device C: ESP32 Autonomous Flying Drone Controller
- **Objective**: Aerial search-and-rescue reconnaissance node.
- **Announcement Packet**:
  ```json
  {
    "type": "announce",
    "client_id": "bupi_uav_01",
    "role": "uav",
    "capabilities": ["Flight_Control", "Altitude_Hold", "Waypoint_3D"],
    "ip_address": "192.168.137.110"
  }
  ```
- **What Can Be Reused**:
  - Tier 1 microsecond regex E-Stop and state dispatch.
  - Tier 2 local Ollama mission decomposition.
  - Mosquitto MQTT broker on `127.0.0.1:1883`.
- **What Must Be Added**:
  - 3D Flight Command Schemas: `takeoff`, `land`, `set_altitude`, `goto_xyz`.
  - MAVLink or MSP UART serial translation bridge.
  - 3D spatial safety validator (altitude ceiling, battery geofence).
- **Python Core Changes Required**: Extension of `core/kinematics_odometry.py` to 3D space $(x, y, z)$.

---

### Hypothetical Device D: Raspberry Pi 5 Tracked Heavy Crawler
- **Objective**: Rugged rubble penetration carrying high-payload gas scrubbers.
- **Announcement Packet**:
  ```json
  {
    "type": "announce",
    "client_id": "bupi_crawler_01",
    "role": "specialist",
    "device_type": "Raspberry_Pi_5",
    "capabilities": ["Motors", "Ultrasonic", "IMU", "Thermal_Camera", "Gas_Array"],
    "ip_address": "192.168.137.120"
  }
  ```
- **What Can Be Reused**:
  - **100% of motor command logic**: The crawler uses differential steering identical to Bot 1 and Bot 2 (`bupi/actuators/motors/cmd/json`).
  - **100% of autonomous mission policies**: `AutonomousGoalAgent` controls linear velocity and heading without caring whether wheels or rubber tracks provide traction.
  - **100% of safety validator**: Gas hazards and obstacle cutoffs work identically.
- **What Must Be Added**:
  - Python listener daemon on Raspberry Pi: `paho.mqtt` client translating motor JSON commands into RPi GPIO or I2C motor driver signals (Cytron / Sabertooth).
- **Python Host Core Changes Required**: **ZERO (0) LINES**.

---
*End of Capability Schemas & Specifications — SIH Problem Statement 26201*
