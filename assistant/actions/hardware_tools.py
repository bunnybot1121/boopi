import paho.mqtt.publish as publish
from crewai.tools import tool

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
    - text: The message to display.
    """
    try:
        topic = "bupi/nodes/desk_display/cmd"
        
        # Optional display validation
        from core.safety_validator import validate_safety
        validation = validate_safety(topic, text)
        if not validation.get("approved", True):
            return f"Blocked: {validation.get('reason')}"
            
        publish.single(topic, text, hostname="localhost")
        return f"Successfully displayed '{text}' on ESP32."
    except Exception as e:
        return f"Failed to display on ESP32: {str(e)}"

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
def read_sensor_status(sensor_id: str) -> str:
    """
    Reads the latest telemetry for a sensor and returns both the raw value and its translated semantic status.
    - sensor_id: The ID of the sensor to query (e.g. 'mq2', 'ir', 'temp', 'humidity', 'distance').
    
    Returns a JSON string representing the sensor state and translation.
    """
    import sqlite3
    import os
    from datetime import datetime
    import json
    from core.sensor_translator import translate_sensor_value
    
    sensor_id = sensor_id.lower()
    synonyms = {
        "mq2": ["mq2"],
        "temp": ["temp", "temperature", "dht", "dht11", "dht22"],
        "temperature": ["temp", "temperature", "dht", "dht11", "dht22"],
        "humidity": ["humidity"],
        "distance": ["distance", "ultrasonic", "hcsr04"],
        "ir": ["ir"]
    }
    
    search_ids = [sensor_id]
    for key, mapped_list in synonyms.items():
        if sensor_id == key or sensor_id in mapped_list:
            search_ids = mapped_list
            break
            
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "bupi_telemetry.db")
    
    try:
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            placeholders = ",".join(["?"] * len(search_ids))
            cursor.execute(
                f"SELECT value, timestamp, sensor_id FROM telemetry WHERE sensor_id IN ({placeholders}) ORDER BY rowid DESC LIMIT 1",
                search_ids
            )
            row = cursor.fetchone()
            conn.close()
            
            if row is not None:
                raw_val, ts, actual_id = row
                translation = translate_sensor_value(actual_id, raw_val)
                dt_str = datetime.fromtimestamp(ts).isoformat()
                return json.dumps({
                    "sensor": actual_id,
                    "raw_value": raw_val,
                    "status": translation["status"],
                    "timestamp": dt_str
                })
    except Exception as e:
        return json.dumps({"error": f"Failed to query database: {str(e)}"})
        
    return json.dumps({
        "sensor": sensor_id,
        "raw_value": 0.0,
        "status": "UNKNOWN",
        "timestamp": datetime.now().isoformat(),
        "info": "No readings found in database yet."
    })

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
            raise SystemExit("Task superseded by a newer command.")
            
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
        except SystemExit:
            raise
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
 
    bridge_obj = None
    try:
        import run_mode2
        bridge_obj = getattr(run_mode2, "hw_bridge", None)
    except Exception:
        pass
 
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

