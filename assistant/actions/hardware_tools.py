import os
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
import paho.mqtt.publish as publish
class CallableTool:
    """
    Ultra-lightweight, 0ms overhead tool wrapper.
    Ensures functions are directly callable as standard Python functions,
    while maintaining .func, .name, and .description attributes for agent frameworks.
    Eliminates 11.5s CrewAI/LiteLLM/Bedrock import blocking on the GUI thread.
    """
    def __init__(self, func, name=None, description=None):
        self.func = func
        self._run = func
        self.run = func
        self.name = name or getattr(func, "__name__", "tool")
        self.description = description or getattr(func, "__doc__", "") or ""
        self.__name__ = getattr(func, "__name__", "tool")
        self.__doc__ = getattr(func, "__doc__", "")

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)

def tool(name_or_func=None, description=None):
    if callable(name_or_func):
        return CallableTool(name_or_func)
    def decorator(f):
        return CallableTool(f, name=name_or_func, description=description)
    return decorator

current_task_id = 0

@tool("Control Hardware Relay")
def control_relay(device_id: str, action: str) -> str:
    """
    Controls a hardware relay on the ESP32.
    - device_id: The exact ID of the device (must be exactly 'relay_1').
    - action: The action to perform (must be exactly 'turn_on' or 'turn_off').
    """
    try:
        state_str = "ON" if action == "turn_on" else "OFF"
        topic = f"bupi/hardware/{device_id}/set"
        
        # Run safety validation before performing control actions
        from core.safety_validator import validate_safety
        validation = validate_safety(topic, state_str)
        if not validation.get("approved", True):
            return f"Blocked: {validation.get('reason')}"
        
        # Publish directly to the local broker
        publish.single(topic, state_str, hostname="localhost")
        
        return f"Successfully sent command {state_str} to {device_id}."
    except Exception as e:
        return f"Failed to control relay: {str(e)}"

@tool("Display Text on ESP32")
def display_on_esp32(text: str) -> str:
    """
    Displays text on the ESP32 screen (LCD/OLED).
    - text: The message to display. Automatically formatted for 16x2 characters.
    """
    try:
        clean_text = str(text).strip()
        # Ensure 16x2 LCD readability
        if len(clean_text) > 16 and "\n" not in clean_text and ":" in clean_text:
            parts = clean_text.split(":", 1)
            line1 = parts[0].strip()[:16]
            line2 = parts[1].strip()[:16]
            formatted_text = f"{line1}\n{line2}"
        else:
            formatted_text = clean_text[:32]
            
        # Optional display validation
        from core.safety_validator import validate_safety
        validation = validate_safety("bupi/actuators/lcd/cmd", formatted_text)
        if not validation.get("approved", True):
            return f"Blocked: {validation.get('reason')}"
            
        # Dual-publish to both display topics to support all firmware versions
        publish.single("bupi/nodes/desk_display/cmd", formatted_text, hostname="localhost")
        publish.single("bupi/actuators/lcd/cmd", formatted_text, hostname="localhost")
        return f"Successfully displayed '{formatted_text}' on ESP32."
    except Exception as e:
        return f"Failed to display on ESP32: {str(e)}"

@tool("Control Robot Motors")
def control_motors(direction: str, speed: int = 255, duration_seconds: float = 1.5, degrees: float = 0.0, robot_id: str = "bupi_01") -> str:
    """
    Controls the mobile base N20 motors via TB6612 driver on the ESP32.
    - direction: 'forward', 'reverse', 'left', 'right', 'stop', or 'turn_by'.
    - speed: PWM motor speed from 0 to 255 (default 255 for full battery torque).
    - duration_seconds: duration in seconds before automatically stopping (default 1.5s, 0 for continuous).
    - degrees: optional angular turn degrees using MPU6050 gyro feedback (e.g. 90 for right 90°, -90 for left 90°).
    - robot_id: Target robot ID, e.g. 'bupi_01' (Scout) or 'bupi_02' (Specialist). Defaults to 'bupi_01'.
    """
    import json
    import time
    import threading
    try:
        direction = str(direction).lower().strip()
        if direction in ["backward", "backwards", "back", "backup", "back_up"]:
            direction = "reverse"
        elif direction in ["ahead", "forward_movement"]:
            direction = "forward"

        try:
            speed_val = int(speed)
        except Exception:
            speed_val = 255

        if speed_val <= 0 and direction != "stop":
            speed = 255
        else:
            speed = max(0, min(255, speed_val))

        try:
            duration_seconds = float(duration_seconds)
        except Exception:
            duration_seconds = 1.5

        try:
            degrees = float(degrees)
        except Exception:
            degrees = 0.0

        target_bot = str(robot_id).strip()
        topics = []
        if target_bot in ["all", "both", "fleet", "bots", "swarm"]:
            topics = ["bupi/actuators/motors/cmd", "bupi/v1/bot2/actuators/motors/cmd"]
        elif target_bot in ["bupi_02", "bot2", "specialist"]:
            topics = ["bupi/v1/bot2/actuators/motors/cmd"]
        else:
            topics = ["bupi/actuators/motors/cmd"]

        # Check if degrees were passed or implied in direction string
        if "90" in direction and "right" in direction:
            degrees = 90.0
        elif "90" in direction and "left" in direction:
            degrees = -90.0
        elif "180" in direction or "u-turn" in direction or "around" in direction:
            degrees = 180.0

        if degrees != 0.0:
            payload = json.dumps({
                "action": "turn_by",
                "degrees": degrees,
                "speed": speed,
                "bot_id": target_bot,
                "robot_id": target_bot
            })
            for top in topics:
                publish.single(f"{top}/json", payload, hostname="localhost")
                publish.single(top, f"turn_by {degrees}", hostname="localhost")
            return f"[{target_bot}] Rotating {degrees}° using closed-loop MPU6050 gyro feedback."

        # Run safety validation against obstacles / collision risk
        from core.safety_validator import validate_safety
        validation = validate_safety(topics[0], direction, bot_id=target_bot)
        if not validation.get("approved", True):
            return f"Blocked: {validation.get('reason')}"
            
        duration_ms = int(duration_seconds * 1000) if duration_seconds > 0 else 0
        payload = json.dumps({
            "action": direction,
            "speed": speed,
            "duration_ms": duration_ms,
            "bot_id": target_bot,
            "robot_id": target_bot
        })
        
        # Publish structured command for ESP32 on all target topics
        for top in topics:
            publish.single(f"{top}/json", payload, hostname="localhost")
            publish.single(top, direction, hostname="localhost")
        
        # Timed auto-stop if duration specified and not already handled
        if duration_seconds > 0 and direction != "stop":
            def auto_stop():
                time.sleep(duration_seconds)
                for top in topics:
                    publish.single(top, "stop", hostname="localhost")
                    publish.single(f"{top}/json", json.dumps({"action": "stop", "speed": 0, "bot_id": target_bot, "robot_id": target_bot}), hostname="localhost")
            threading.Thread(target=auto_stop, daemon=True).start()
            return f"[{target_bot}] Motors moving {direction} at speed {speed} for {duration_seconds}s."
            
        return f"[{target_bot}] Motors set to {direction} (speed {speed}, continuous)."
    except Exception as e:
        return f"Failed to control motors: {str(e)}"

@tool("Toggle Edge Obstacle Avoidance")
def toggle_edge_avoidance(enabled: bool = True, robot_id: str = "bupi_01") -> str:
    """
    Enables or disables 100% onboard edge-computing obstacle avoidance and autonomous roaming on the ESP32.
    - enabled: True to start autonomous edge roaming and collision evasion, False to halt and standby.
    - robot_id: Target robot ID, e.g. 'bupi_01' (Scout) or 'bupi_02' (Specialist). Defaults to 'bupi_01'.
    """
    import json
    try:
        target_bot = str(robot_id).strip()
        if target_bot in ["bupi_02", "bot2"]:
            topic = "bupi/v1/bot2/actuators/motors/cmd/json"
        else:
            topic = "bupi/actuators/motors/cmd/json"

        payload = json.dumps({
            "action": "auto_avoid",
            "enabled": bool(enabled),
            "bot_id": target_bot,
            "robot_id": target_bot
        })
        publish.single(topic, payload, hostname="localhost")
        if enabled:
            return f"[{target_bot}] Autonomous edge obstacle avoidance enabled. ESP32 is now navigating onboard."
        else:
            return f"[{target_bot}] Autonomous edge obstacle avoidance disabled. Robot halted and in standby."
    except Exception as e:
        return f"Failed to toggle edge avoidance: {str(e)}"

@tool("Universal MQTT Hardware Controller")
def universal_mqtt_tool(topic: str, payload: str) -> str:
    """
    Sends an arbitrary MQTT payload to a specific topic to control any trained hardware.
    - topic: The MQTT topic to publish to.
    - payload: The message or command to send.
    """
    try:
        # Run safety validation before publishing arbitrary hardware commands
        from core.safety_validator import validate_safety
        validation = validate_safety(topic, payload)
        if not validation.get("approved", True):
            return f"Blocked: {validation.get('reason')}"
            
        publish.single(topic, payload, hostname="localhost")
        return f"Successfully published payload '{payload}' to topic '{topic}'."
    except Exception as e:
        return f"Failed to publish to MQTT: {str(e)}"

@tool("Read Translated Sensor Status")
def read_sensor_status(sensor_id: str, robot_id: str = "") -> str:
    """
    Reads the latest telemetry for a sensor and returns both the raw value, calibrated real-world value, and conversational semantic status.
    - sensor_id: The ID of the sensor to query (e.g. 'mq2', 'gas', 'temp', 'temperature', 'humidity', 'distance', 'pir', 'motion').
    - robot_id: Optional target robot ID ('bupi_01' for Scout, 'bupi_02' for Specialist). If omitted, automatically routes to the capable robot.
    
    Returns a JSON string representing the sensor state and real-life translation.
    """
    import sqlite3
    import os
    from datetime import datetime
    import json
    from core.sensor_translator import translate_sensor_value
    
    sensor_id = str(sensor_id).lower().strip()
    synonyms = {
        "mq2": ["mq2", "gas", "smoke", "air_quality"],
        "temp": ["temp", "temperature", "dht", "dht11", "dht22", "climate"],
        "temperature": ["temp", "temperature", "dht", "dht11", "dht22", "climate"],
        "humidity": ["humidity"],
        "distance": ["distance", "ultrasonic", "hcsr04", "clearance"],
        "ir": ["ir"],
        "pir": ["pir", "motion"]
    }
    
    search_ids = [sensor_id]
    for key, mapped_list in synonyms.items():
        if sensor_id == key or sensor_id in mapped_list:
            search_ids = mapped_list
            break
            
    # Capability-aware candidate robot ordering
    req_bot = str(robot_id).lower().strip()
    if "2" in req_bot or "specialist" in req_bot or "hazard" in req_bot:
        candidate_bots = ["bupi_02"]
    elif "1" in req_bot or "scout" in req_bot:
        candidate_bots = ["bupi_01"]
    elif any(k in sensor_id for k in ["mq2", "gas", "smoke", "temp", "temperature", "dht", "humidity"]):
        # Environmental sensing is Bot 2's exclusive hardware capability
        candidate_bots = ["bupi_02", "bupi_01"]
    elif any(k in sensor_id for k in ["pir", "motion"]):
        # PIR human thermal motion is Bot 1's exclusive hardware capability
        candidate_bots = ["bupi_01"]
    else:
        candidate_bots = ["bupi_01", "bupi_02"]

    # Filter search_ids strictly according to target candidate_bots
    search_ids = list(search_ids)
    extra_ids = []
    for c_bot in candidate_bots:
        for sid in search_ids:
            extra_ids.append(f"{c_bot}_{sid}")
    search_ids.extend(extra_ids)

    # 1. First check high-speed in-memory live telemetry from bupi_node_server
    try:
        import time
        from bupi_node_server import get_latest_telemetry
        now = time.time()
        for candidate_bot in candidate_bots:
            live_t = get_latest_telemetry(candidate_bot)
            if live_t and live_t.get("updated_at", 0) > 0 and (now - live_t.get("updated_at", 0)) < 30.0:
                if sensor_id in ["distance", "ultrasonic", "hcsr04", "clearance"]:
                    dist_cm = float(live_t.get("distance_cm", 150.0))
                    trans = translate_sensor_value("distance", dist_cm)
                    return json.dumps({
                        "sensor": "distance",
                        "robot_id": candidate_bot,
                        "value": trans["value"],
                        "raw_value": dist_cm,
                        "status": trans["status"],
                        "description": trans["description"],
                        "obstacle_detected": bool(dist_cm < 35.0),
                        "timestamp": datetime.fromtimestamp(live_t.get("updated_at", now)).isoformat()
                    })
                elif sensor_id in ["mq2", "gas", "smoke", "air_quality"]:
                    mq2_val = float(live_t.get("gas_ppm", live_t.get("mq2_raw", 35.0)))
                    trans = translate_sensor_value("mq2", mq2_val)
                    return json.dumps({
                        "sensor": "mq2",
                        "robot_id": candidate_bot,
                        "value": trans["value"],
                        "raw_value": mq2_val,
                        "status": trans["status"],
                        "description": trans["description"],
                        "timestamp": datetime.fromtimestamp(live_t.get("updated_at", now)).isoformat()
                    })
                elif sensor_id in ["temp", "temperature", "dht", "climate"]:
                    t_val = float(live_t.get("temp_c", live_t.get("temperature_c", 24.5)))
                    trans = translate_sensor_value("temperature", t_val)
                    return json.dumps({
                        "sensor": "temperature",
                        "robot_id": candidate_bot,
                        "value": trans["value"],
                        "raw_value": t_val,
                        "status": trans["status"],
                        "description": trans["description"],
                        "timestamp": datetime.fromtimestamp(live_t.get("updated_at", now)).isoformat()
                    })
                elif sensor_id in ["humidity"]:
                    h_val = float(live_t.get("humidity", 48.0))
                    trans = translate_sensor_value("humidity", h_val)
                    return json.dumps({
                        "sensor": "humidity",
                        "robot_id": candidate_bot,
                        "value": trans["value"],
                        "raw_value": h_val,
                        "status": trans["status"],
                        "description": trans["description"],
                        "timestamp": datetime.fromtimestamp(live_t.get("updated_at", now)).isoformat()
                    })
                elif sensor_id in ["pir", "motion"]:
                    p_val = int(live_t.get("pir", 0))
                    last_pir_t = float(live_t.get("last_pir_time", 0.0))
                    age_recent = now - last_pir_t if last_pir_t > 0 else 999999.0

                    if p_val == 1:
                        status = "MOTION_DETECTED"
                        desc = "Active thermal infrared motion detected! Person moving in room right now."
                        p_val = 1
                        person_detected = True
                    elif age_recent <= 30.0:
                        status = "RECENT_MOTION_DETECTED"
                        desc = f"Human presence confirmed! Thermal infrared motion detected {age_recent:.1f} seconds ago."
                        p_val = 1
                        person_detected = True
                    else:
                        status = "AREA_QUIET"
                        desc = "No motion detected; surrounding area has been quiet for over 30 seconds."
                        person_detected = False

                    return json.dumps({
                        "sensor": "pir",
                        "robot_id": candidate_bot,
                        "value": "MOTION_DETECTED" if person_detected else "AREA_QUIET",
                        "raw_value": p_val,
                        "status": status,
                        "description": desc,
                        "person_detected": person_detected,
                        "age_seconds": round(age_recent, 1) if last_pir_t > 0 else None,
                        "timestamp": datetime.fromtimestamp(live_t.get("updated_at", now)).isoformat()
                    })
    except Exception:
        pass

    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(base_dir, "bupi_telemetry.db")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(search_ids))

            # If querying motion/pir, check if motion was triggered within the last 30 seconds
            if any(k in sensor_id for k in ["pir", "motion"]):
                cursor.execute(
                    f"SELECT timestamp FROM telemetry WHERE sensor_id IN ({placeholders}) AND value >= 1.0 AND timestamp >= ? ORDER BY timestamp DESC LIMIT 1",
                    search_ids + [time.time() - 30.0]
                )
                motion_row = cursor.fetchone()
                if motion_row:
                    m_ts = motion_row[0]
                    m_age = time.time() - m_ts
                    conn.close()
                    return json.dumps({
                        "sensor": "pir",
                        "robot_id": candidate_bots[0],
                        "value": "MOTION_DETECTED",
                        "raw_value": 1,
                        "status": "RECENT_MOTION_DETECTED",
                        "description": f"Human presence confirmed! Thermal infrared motion detected {m_age:.1f} seconds ago.",
                        "person_detected": True,
                        "age_seconds": round(m_age, 1),
                        "timestamp": datetime.fromtimestamp(m_ts).isoformat()
                    })

            cursor.execute(
                f"SELECT value, timestamp, sensor_id FROM telemetry WHERE sensor_id IN ({placeholders}) ORDER BY rowid DESC LIMIT 1",
                search_ids
            )
            row = cursor.fetchone()
            conn.close()
            
            if row is not None:
                raw_val, ts, actual_id = row
                import time
                age = time.time() - ts if ts else 999999.0
                canonical_sensor = actual_id.replace("bupi_01_", "").replace("bupi_02_", "")
                trans = translate_sensor_value(canonical_sensor, float(raw_val))
                return json.dumps({
                    "sensor": canonical_sensor,
                    "robot_id": candidate_bots[0],
                    "raw_sensor_id": actual_id,
                    "value": trans["value"],
                    "raw_value": float(raw_val),
                    "status": trans["status"],
                    "description": trans["description"],
                    "age_seconds": round(age, 1),
                    "timestamp": datetime.fromtimestamp(ts).isoformat() if ts else None
                })
    except Exception:
        pass

    # Unconfigured / clean fallback
    fallback_trans = translate_sensor_value(sensor_id, 0.0)
    return json.dumps({
        "sensor": sensor_id,
        "robot_id": candidate_bots[0],
        "value": fallback_trans["value"],
        "raw_value": 0.0,
        "status": fallback_trans["status"],
        "description": fallback_trans["description"],
        "note": "Standard calibrated baseline"
    })

@tool("Read Environmental State")
def read_environmental_state(robot_id: str = "bupi_02") -> str:
    """
    Reads the complete environmental and hazard telemetry for Bot 2 (Specialist)
    including MQ-2 gas concentration (ppm), ambient temperature (°C), and relative humidity (%).
    - robot_id: Robot ID to query, defaults to 'bupi_02'.
    """
    import json
    import time
    from core.safety_validator import get_current_world_state
    try:
        from bupi_node_server import get_latest_telemetry
        telem = get_latest_telemetry(robot_id)
        now = time.time()
        is_live = (telem.get("updated_at", 0) > 0) and ((now - telem.get("updated_at", 0)) < 15.0)
        if not is_live:
            return json.dumps({
                "robot_id": robot_id,
                "status": "OFFLINE",
                "gas_status": "OFFLINE",
                "temperature_status": "OFFLINE",
                "humidity_status": "OFFLINE",
                "info": f"Robot {robot_id} is currently offline. No live environmental sensor readings available."
            })
        ws = get_current_world_state(bot_id=robot_id)
        return json.dumps({
            "robot_id": robot_id,
            "status": "ONLINE",
            "gas_ppm": telem.get("gas_ppm", telem.get("mq2_raw", 0.0)),
            "gas_status": ws.get("gas", "SAFE"),
            "temperature_c": telem.get("temp_c", telem.get("temperature_c", 25.0)),
            "temperature_status": ws.get("temperature", "COMFORTABLE"),
            "humidity_pct": telem.get("humidity", 50.0),
            "humidity_status": ws.get("humidity", "NORMAL"),
            "distance_cm": telem.get("distance_cm", 150.0),
            "heading_deg": telem.get("heading", 0.0),
            "tilt_deg": telem.get("effective_tilt", 0.0)
        })
    except Exception as e:
        return json.dumps({"error": f"Failed to read environmental state: {str(e)}"})

@tool("Get Environment World State")
def get_world_state() -> str:
    """
    Aggregates all sensor readings into a single environment snapshot.
    Returns a JSON string representing the environment's current semantic state.
    Use this tool as the primary way to check the overall environment before deciding actions.
    """
    from core.safety_validator import get_current_world_state
    import json
    return json.dumps(get_current_world_state())

@tool("Read MQTT Sensor Data")
def read_mqtt_sensor(topic: str) -> str:
    """
    Subscribes to an MQTT topic briefly to read the latest sensor telemetry or state value.
    - topic: The MQTT topic to listen to (e.g. 'bupi/sensors/dht/temperature').
    """
    import paho.mqtt.client as mqtt
    import time
    
    timeout = 2.0
    received_payload = None
    
    def on_message(client, userdata, msg):
        nonlocal received_payload
        received_payload = msg.payload.decode('utf-8', errors='ignore')
        
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    
    try:
        client.connect("localhost", 1883, 60)
        client.subscribe(topic)
        
        start_time = time.time()
        client.loop_start()
        
        while received_payload is None and (time.time() - start_time) < timeout:
            time.sleep(0.05)
            
        client.loop_stop()
        client.disconnect()
    except Exception as e:
        return f"Error subscribing to {topic}: {str(e)}"
        
    if received_payload is not None:
        return f"Success: Received state '{received_payload}' on topic '{topic}'."
    else:
        return f"Timeout: No message received on {topic} within {timeout}s."

@tool("Execute Robotic Python Code")
def run_robotic_code(script_code: str) -> str:
    """
    Executes a custom Python script for complex, closed-loop robotic control.
    Use this when you need real-time loops, conditional logic, or search algorithms
    that combine motor controls and sensor inputs (e.g. searching for the hottest spot).
    
    CRITICAL FOR CONTINUOUS AUTOMATIONS/TRIGGERS:
    If the user's task is a continuous automation or event listener (e.g. "whenever a sensor reading changes, update the display"), the script MUST NOT block the main thread. Instead, you MUST spawn a background thread using `threading.Thread(target=your_loop_function, daemon=True).start()` and print a success message. This allows the script to exit immediately while the loop runs in the background. Import the `threading` library inside your script.

    SAFETY WARNING:
    All commands sent via `publish()` are run through a Safety Validation Layer.
    Dangerous actions (e.g. moving forward when collision risk is high) will raise a ValueError.

    The script has access to helper functions and objects:
    1. publish(topic, payload) -> None
       Sends an MQTT payload to a topic (safety validated).
    2. subscribe(topic, timeout=2.0) -> str
       Listens to an MQTT topic and returns the next payload, or None if it times out.
    3. get_world_state() -> dict
       Returns a snapshot of the current semantic world state:
       e.g. {"gas": "SAFE", "temperature": "COMFORTABLE", "humidity": "NORMAL", "distance": "CLEAR", "ir": "CLEAR"}
    4. translate_sensor_value(sensor_id, value) -> dict
       Returns semantic details for a specific sensor and reading.
    5. bridge -> The active MQTTBridge instance (or None if offline).
       You can access its live telemetry memory:
       - bridge.values_histories (dict mapping sensor_id strings to list of floats, e.g. bridge.values_histories.get("mq2", []))
       - bridge.highest_vals, bridge.lowest_vals
       - SQLite database query helper methods:
         * bridge.get_historical_readings(sensor_id, limit=100) -> list of dict (e.g. [{"timestamp": ..., "value": ...}])
         * bridge.get_average_reading(sensor_id, since_seconds=None) -> float (since_seconds is relative, e.g., 60 for last 1 min)
         * bridge.get_max_reading(sensor_id, since_seconds=None) -> float
         * bridge.get_min_reading(sensor_id, since_seconds=None) -> float
         * bridge.get_sensor_status(sensor_id) -> dict (semantic translation: e.g. {"sensor": "mq2", "value": 2415, "status": "DANGER", "description": "Dangerous concentration of smoke or flammable gas!"})
        
    Make sure your script prints its final results or path using standard print().
    """
    import io
    import sys
    import time
    import paho.mqtt.client as mqtt
    import paho.mqtt.publish as pub
    from core.sensor_translator import translate_sensor_value
    from core.safety_validator import get_current_world_state as get_world_state, validate_safety
    
    global current_task_id
    current_task_id += 1
    my_task_id = current_task_id
    
    stdout_buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout_buf
    
    def check_superseded():
        if my_task_id < current_task_id:
            raise RuntimeError("Task superseded by a newer command.")
            
    def publish(topic, payload):
        check_superseded()
        
        # Safety validation check
        validation = validate_safety(topic, payload)
        if not validation.get("approved", True):
            reason = validation.get("reason", "Safety validation failed.")
            print(f"[Robot System Blocked] Safety Block: {reason}")
            raise ValueError(f"Safety Block: {reason}")
            
        pub.single(topic, str(payload), hostname="localhost")
        print(f"[Robot System] Published: {payload} -> {topic}")
        
    def subscribe(topic, timeout=2.0):
        check_superseded()
        received_payload = None
        
        def on_message(client, userdata, msg):
            nonlocal received_payload
            received_payload = msg.payload.decode('utf-8', errors='ignore')
            
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_message = on_message
        
        try:
            client.connect("localhost", 1883, 60)
            client.subscribe(topic)
            
            start_time = time.time()
            client.loop_start()
            
            while received_payload is None and (time.time() - start_time) < timeout:
                check_superseded()
                time.sleep(0.05)
                
            client.loop_stop()
            client.disconnect()
        except Exception as e:
            print(f"[Robot System Error] Subscribe error on {topic}: {e}")
            
        return received_payload
 
    def sleep_wrapper(seconds):
        check_superseded()
        time.sleep(seconds)
 
    class CustomTime:
        def __init__(self):
            self.sleep = sleep_wrapper
        def __getattr__(self, name):
            return getattr(time, name)
            
    custom_time = CustomTime()
 
    bridge_obj = getattr(sys.modules.get("actions.hardware_tools"), "active_bridge", None)
 
    exec_globals = {
        "publish": publish,
        "subscribe": subscribe,
        "time": custom_time,
        "print": print,
        "bridge": bridge_obj,
        "translate_sensor_value": translate_sensor_value,
        "get_world_state": get_world_state
    }
    
    try:
        # Strip potential markdown code fences from the LLM generated script
        cleaned_code = script_code
        if cleaned_code.startswith("```python"):
            cleaned_code = cleaned_code[9:]
        elif cleaned_code.startswith("```"):
            cleaned_code = cleaned_code[3:]
        if cleaned_code.endswith("```"):
            cleaned_code = cleaned_code[:-3]
        cleaned_code = cleaned_code.strip()
        
        exec(cleaned_code, exec_globals)
        success = True
    except Exception as e:
        print(f"Execution Error: {e}")
        success = False
    finally:
        sys.stdout = old_stdout
        
    output = stdout_buf.getvalue()
    return f"Status: {'SUCCESS' if success else 'FAILED'}\nOutput:\n{output}"

@tool("Query Hardware Knowledge Base")
def get_hardware_knowledge(component_name: str) -> str:
    """
    Retrieves complete offline hardware specifications, pinouts, wiring instructions, 
    truth tables, and common pitfalls for robotics components (e.g. 'TB6612FNG', 'HC-SR04', 'MPU6050', 'MQ2', 'RELAY', 'ESP32_PINOUT').
    - component_name: The name or type of the hardware component to look up.
    """
    import os
    import json
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cache_path = os.path.join(base_dir, "brain", "sensor_knowledge_cache.json")
        if os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Match exact or partial key (case-insensitive)
            comp_clean = component_name.strip().upper().replace("-", "").replace("_", "")
            for key, val in data.items():
                key_clean = key.strip().upper().replace("-", "").replace("_", "")
                if comp_clean in key_clean or key_clean in comp_clean:
                    return json.dumps(val, indent=2)
            # If not found, list available components
            return f"Component '{component_name}' not found in offline knowledge cache. Available components: {list(data.keys())}"
        return "Hardware knowledge cache not found."
    except Exception as e:
        return f"Failed to retrieve hardware knowledge: {str(e)}"

@tool("Get Connected ESP32 Nodes")
def get_connected_nodes() -> str:
    """
    Returns the list of active ESP32 nodes connected to the MQTT broker, including their
    IP addresses, capabilities, tasks, and how many seconds ago they sent a heartbeat.
    """
    import os
    import sqlite3
    import time
    import json
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "bupi_telemetry.db")
    try:
        if not os.path.exists(db_path):
            return json.dumps({"connected_nodes": [], "message": "Telemetry database not initialized yet."})
            
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nodes'")
        if not cursor.fetchone():
            conn.close()
            return json.dumps({"connected_nodes": [], "message": "No nodes registered yet. Waiting for ESP32 heartbeat."})
            
        # Check if telemetry table has fresh sensor readings (< 15s)
        recent_telemetry = False
        try:
            cursor.execute("SELECT timestamp FROM telemetry ORDER BY rowid DESC LIMIT 1")
            t_row = cursor.fetchone()
            if t_row and t_row[0] and (now - float(t_row[0])) < 15.0:
                recent_telemetry = True
        except Exception:
            pass

        cursor.execute("SELECT client_id, device_name, ip_address, capabilities, last_heartbeat, status FROM nodes ORDER BY last_heartbeat DESC")
        rows = cursor.fetchall()
        conn.close()
        
        now = time.time()
        nodes = []
        for r in rows:
            client_id, device_name, ip_addr, caps, last_hb, status = r
            delta_sec = round(now - last_hb, 1) if last_hb else None
            # Consider online if heartbeat was within 60s OR if recent telemetry is flowing
            is_online = (delta_sec is not None and delta_sec < 60.0) or recent_telemetry
            
            parsed_caps = caps
            if caps:
                try:
                    parsed_caps = json.loads(caps)
                except Exception:
                    try:
                        import ast
                        parsed_caps = ast.literal_eval(caps)
                    except Exception:
                        parsed_caps = [caps]
                        
            nodes.append({
                "client_id": client_id,
                "device_name": device_name,
                "ip_address": ip_addr,
                "capabilities": parsed_caps,
                "last_seen_seconds_ago": 0.0 if (recent_telemetry and not (delta_sec is not None and delta_sec < 15.0)) else delta_sec,
                "status": "ONLINE" if is_online else "OFFLINE"
            })

        # Also incorporate any WebSocket nodes from bupi_node_server
        try:
            from bupi_node_server import live_nodes, live_nodes_lock
            with live_nodes_lock:
                for nid, ninfo in live_nodes.items():
                    if not any(n["client_id"] == nid for n in nodes):
                        nodes.append({
                            "client_id": nid,
                            "device_name": ninfo.get("device", "ESP32 LCD Client"),
                            "ip_address": ninfo.get("ip", "unknown"),
                            "capabilities": ninfo.get("capabilities", ["Display"]),
                            "last_seen_seconds_ago": round(now - ninfo.get("last_seen", now), 1),
                            "status": "ONLINE" if ninfo.get("status") == "online" else "OFFLINE"
                        })
        except Exception:
            pass

        return json.dumps({"connected_nodes": nodes, "total_nodes": len(nodes)}, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Failed to query connected nodes: {str(e)}"})

@tool("Start Autonomous Robotic Mission")
def start_autonomous_mission(mission_description: str) -> str:
    """
    Decomposes and starts an autonomous closed-loop robotic mission (e.g. 'find the human in the room',
    'patrol and inspect gas', 'explore and avoid obstacles') where Boopi navigates, senses, and avoids obstacles by itself.
    - mission_description: High-level goal or mission for the robot to complete autonomously.
    """
    try:
        from agents.autonomous_goal_agent import goal_agent
        return goal_agent.start_mission(mission_description)
    except Exception as e:
        return f"Failed to launch autonomous mission: {str(e)}"

@tool("Stop Active Autonomous Mission")
def stop_current_mission() -> str:
    """
    Immediately stops any currently running autonomous mission, halting all motors and returning Boopi to standby.
    """
    try:
        from agents.autonomous_goal_agent import goal_agent
        return goal_agent.stop_mission(reason="Operator request")
    except Exception as e:
        return f"Failed to stop autonomous mission: {str(e)}"

@tool("Bypass Obstacle")
def bypass_obstacle(robot_id: str = "bupi_01", direction: str = "auto") -> str:
    """
    Executes an active flank-and-detour obstacle bypass maneuver ('cross out the obstacle')
    on the specified robot (Bot 1 Scout or Bot 2 Specialist).
    - robot_id: Target robot, 'bupi_01' or 'bupi_02'.
    - direction: 'auto', 'left', or 'right'.
    """
    try:
        from core.obstacle_bypass_engine import execute_obstacle_bypass
        res = execute_obstacle_bypass(bot_id=robot_id, flank_direction=direction)
        return res.get("summary", "Bypass maneuver executed.")
    except Exception as e:
        return f"Failed to execute obstacle bypass: {str(e)}"

@tool("Get Swarm State")
def get_swarm_status() -> str:
    """
    Retrieves the live synchronized collaborative state of both Bot 1 (Scout) and Bot 2 (Specialist).
    """
    try:
        from core.swarm_coordinator import swarm_coordinator
        import json
        return json.dumps(swarm_coordinator.coordinate_tandem_reading(), indent=2)
    except Exception as e:
        return f"Failed to retrieve swarm state: {str(e)}"

@tool("Get Odometry and Wi-Fi Range")
def get_odometry_and_wifi_range(robot_id: str = "bupi_01") -> str:
    """
    Retrieves the live MPU6050 step count, Cartesian coordinates (X, Y in meters),
    total distance traveled, and estimated Wi-Fi distance from the host laptop/Boopi Hub.
    - robot_id: Target robot ID, 'bupi_01' (Scout) or 'bupi_02' (Specialist).
    """
    try:
        from core.kinematics_odometry import odometry_engine
        import json
        target_bot = "bupi_02" if "2" in str(robot_id) else "bupi_01"
        return json.dumps(odometry_engine.get_state(target_bot), indent=2)
    except Exception as e:
        return f"Failed to retrieve odometry and range: {str(e)}"

