import paho.mqtt.publish as publish
from crewai.tools import tool

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
        publish.single(topic, payload, hostname="localhost")
        return f"Successfully published payload '{payload}' to topic '{topic}'."
    except Exception as e:
        return f"Failed to publish to MQTT: {str(e)}"

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

    The script has access to two built-in helper functions:
    1. publish(topic, payload) -> None
       Sends an MQTT payload to a topic.
    2. subscribe(topic, timeout=2.0) -> str
       Listens to an MQTT topic and returns the next payload, or None if it times out.
       
    Make sure your script prints its final results or path using standard print().
    """
    import io
    import sys
    import time
    import paho.mqtt.client as mqtt
    import paho.mqtt.publish as pub
    
    stdout_buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = stdout_buf
    
    def publish(topic, payload):
        pub.single(topic, str(payload), hostname="localhost")
        print(f"[Robot System] Published: {payload} -> {topic}")
        
    def subscribe(topic, timeout=2.0):
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
            print(f"[Robot System Error] Subscribe error on {topic}: {e}")
            
        return received_payload

    exec_globals = {
        "publish": publish,
        "subscribe": subscribe,
        "time": time,
        "print": print
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

