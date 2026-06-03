import sys
# Reconfigure stdout/stderr to UTF-8 to prevent cp1252 charmap encoding errors on Windows console
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

import asyncio
import json
import paho.mqtt.client as mqtt
from core.event_bus_async import bus
from core.mqtt_bridge import MQTTBridge
import threading
from agents.robotic_crew import run_robotic_task

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
LISTEN_TOPIC = "bupi/internal/utterance"

hw_bridge = None
import random
# Create a second MQTT client specifically to listen for utterances from Mode 1
m2_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"Mode2_Runner_{random.randint(0, 9999)}")

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"[Mode 2] Connected. Listening for utterances on {LISTEN_TOPIC}", flush=True)
    client.subscribe(LISTEN_TOPIC)
    client.subscribe("bupi/nodes/announce")
    client.subscribe("bupi/nodes/heartbeat")

def on_message(client, userdata, msg):
    if msg.topic == LISTEN_TOPIC:
        try:
            payload = json.loads(msg.payload.decode())
            text = payload.get("text", "")
            if text:
                print(f"\n[Mode 2] Received Utterance from Mode 1: '{text}'", flush=True)
                # Offload to CrewAI in a separate thread so we don't block MQTT loop
                threading.Thread(target=process_with_crew, args=(text,), daemon=True).start()
        except Exception as e:
            print(f"[Mode 2] Error parsing utterance: {e}", flush=True)
    elif msg.topic in ["bupi/nodes/announce", "bupi/nodes/heartbeat"]:
        try:
            payload = json.loads(msg.payload.decode())
            node_id = payload.get("client_id", "MQTT_Unknown")
            device = payload.get("device", "MQTT Node")
            ip = payload.get("ip", "N/A")
            capabilities = payload.get("capabilities", ["MQTT"])
            tasks = payload.get("tasks", ["General MQTT Client"])
            
            from bupi_node_server import register_node, update_node_heartbeat
            if msg.topic == "bupi/nodes/announce":
                register_node(node_id, ip, "MQTT", device, capabilities, tasks)
                print(f"[Mode 2] Dynamically registered MQTT Node: {node_id} ({device})", flush=True)
            else:
                update_node_heartbeat(node_id)
        except Exception as e:
            print(f"[Mode 2] Error parsing MQTT Node announce/heartbeat: {e}", flush=True)

def get_sensor_id_from_text(text):
    """
    Scans hardware_memory.txt for registered MQTT sensor topics and returns the matched sensor_id
    if present in the text, otherwise falls back to synonym matching or the latest registered sensor.
    """
    cleaned = text.lower()
    
    # 1. Read hardware_memory.txt to extract all trained sensor IDs
    import os, re
    mem_path = os.path.join(os.path.dirname(__file__), "hardware_memory.txt")
    registered_sensors = []
    if os.path.exists(mem_path):
        try:
            with open(mem_path, "r", encoding="utf-8") as f:
                content = f.read()
                # Find all occurrences of bupi/sensors/<sensor_id>/state or MQTT_RECEIVE topics
                matches = re.findall(r"bupi/sensors/(\w+)/state", content)
                for m in matches:
                    sensor_name = m.lower()
                    if sensor_name not in registered_sensors:
                        registered_sensors.append(sensor_name)
        except Exception as e:
            print(f"[Mode 2 Error] Failed to read hardware memory: {e}", flush=True)
            
    # Always include standard defaults
    if "mq2" not in registered_sensors:
        registered_sensors.append("mq2")

    # 2. Check if any registered sensor is explicitly mentioned in the text
    for sensor in registered_sensors:
        if sensor in cleaned:
            return sensor
            
    # 3. Check for common synonyms
    if "gas" in cleaned or "smoke" in cleaned:
        return "mq2"
    if "temp" in cleaned or "temperature" in cleaned:
        # Check if temperature maps to temp or dht11 in registered sensors
        for s in ["temp", "dht11", "dht22", "dht"]:
            if s in registered_sensors:
                return s
        return "temp"
    if "humidity" in cleaned:
        for s in ["humidity", "dht11", "dht22", "dht"]:
            if s in registered_sensors:
                return s
        return "humidity"
    if "distance" in cleaned or "ultrasonic" in cleaned:
        for s in ["distance", "ultrasonic", "hcsr04", "hcsro4"]:
            if s in registered_sensors:
                return s
        return "distance"
        
    # 4. Default fallback: use the last registered sensor in hardware_memory.txt
    if len(registered_sensors) > 0:
        # Skip 'mq2' if there is another more recently trained sensor
        custom_sensors = [s for s in registered_sensors if s != "mq2"]
        if custom_sensors:
            return custom_sensors[-1]
            
    return "mq2"

def process_with_crew(text):
    global hw_bridge
    cleaned = text.lower()
    
    # Deterministic telemetry routing to handle all display & MQ2 commands robustly
    sensor_words = ["mq2", "gas", "smoke", "sensor", "reading", "readings", "value", "values", "data", "val", "level", "levels", "ppm", "temp", "temperature", "humidity", "distance", "ultrasonic"]
    display_words = ["lcd", "display", "screen", "unit", "show", "output", "view", "relay"]
    
    sensor_id = get_sensor_id_from_text(text)
    sensor_name = sensor_id.upper()
    
    has_sensor = any(w in cleaned for w in sensor_words) or (sensor_id in cleaned)
    has_display = any(w in cleaned for w in display_words)
    
    # Identify if the request contains any conditional logic (for custom closed-loop script generation)
    conditional_words = ["if", "when", "whenever", "once", "greater", "less", "above", "below", "under", "exceed", "exceeds", "threshold", "trigger", "higher than", "lower than", ">", "<", "="]
    is_conditional = any(f" {w} " in f" {cleaned} " or cleaned.startswith(w) or cleaned.endswith(w) for w in conditional_words)
    
    if (has_sensor or has_display) and not is_conditional:
        if any(w in cleaned for w in ["stop", "turn off", "disable", "clear", "remove", "reset"]):
            if hw_bridge:
                hw_bridge.set_sensor_mode(sensor_id, None)
                
                # Check if any telemetry modes remain active
                active_sensors = [s for s, mode in hw_bridge.telemetry_modes.items() if mode is not None]
                if not active_sensors:
                    # Clear the display if no sensors are active
                    hw_bridge.client.publish("bupi/actuators/lcd/cmd", " ")
                    response = "I have stopped displaying the sensor readings on the LCD."
                else:
                    response = f"I have stopped displaying the {sensor_name} sensor readings on the LCD."
                    
                print(f"[Mode 2] Deterministic route: {response}", flush=True)
                m2_client.publish("bupi/internal/tts", json.dumps({"text": response}))
                return
                
        elif any(w in cleaned for w in ["highest", "maximum", "max", "peak"]):
            if hw_bridge:
                hw_bridge.set_sensor_mode(sensor_id, "highest")
                response = f"I am now tracking and displaying the highest {sensor_name} sensor readings on the display unit."
                print(f"[Mode 2] Deterministic route: {response}", flush=True)
                m2_client.publish("bupi/internal/tts", json.dumps({"text": response}))
                return
                
        elif any(w in cleaned for w in ["lowest", "minimum", "min"]):
            if hw_bridge:
                hw_bridge.set_sensor_mode(sensor_id, "lowest")
                response = f"I am now tracking and displaying the lowest {sensor_name} sensor readings on the display unit."
                print(f"[Mode 2] Deterministic route: {response}", flush=True)
                m2_client.publish("bupi/internal/tts", json.dumps({"text": response}))
                return
                
        elif any(w in cleaned for w in ["average", "avg", "mean"]):
            if hw_bridge:
                hw_bridge.set_sensor_mode(sensor_id, "average")
                response = f"I am now calculating and displaying the running average of the {sensor_name} sensor readings on the display unit."
                print(f"[Mode 2] Deterministic route: {response}", flush=True)
                m2_client.publish("bupi/internal/tts", json.dumps({"text": response}))
                return
                
        elif any(w in cleaned for w in ["continuous", "current", "realtime", "live", "real-time"]) or ("display" in cleaned or "show" in cleaned or "relay" in cleaned or "view" in cleaned):
            if hw_bridge:
                hw_bridge.set_sensor_mode(sensor_id, "continuous")
                response = f"I have enabled the continuous {sensor_name} sensor display on the LCD."
                print(f"[Mode 2] Deterministic route: {response}", flush=True)
                m2_client.publish("bupi/internal/tts", json.dumps({"text": response}))
                return

    max_retries = 3
    import time
    for attempt in range(max_retries):
        try:
            print(f"\n--- [ROBOT] KICKING OFF CREW AI (Attempt {attempt + 1}) ---", flush=True)
            response = run_robotic_task(text)
            print(f"--- [ROBOT] CREW AI FINISHED ---", flush=True)
            print(f"Result: {response}", flush=True)
            # Send TTS back to Mode 1
            m2_client.publish("bupi/internal/tts", json.dumps({"text": response}))
            return # Success, exit function
        except Exception as e:
            print(f"[Mode 2] CrewAI Attempt {attempt + 1} Error: {e}", flush=True)
            if attempt < max_retries - 1:
                print("[Mode 2] Rotating key and retrying in 5 seconds...", flush=True)
                time.sleep(5)
            else:
                m2_client.publish("bupi/internal/tts", json.dumps({"text": "Sorry, my robotic crew encountered an error."}))

# Catch the TTS intent from the RouterAgent and push it back to Mode 1
async def send_tts_to_mode1(payload):
    text = payload.get("text", "")
    if text:
        print(f"[Mode 2] Sending TTS back to Mode 1: '{text}'", flush=True)
        m2_client.publish("bupi/internal/tts", json.dumps({"text": text}))

async def main():
    global loop
    loop = asyncio.get_running_loop()

    global hw_bridge
    # 1. Start the MQTT Bridge (handles any raw hardware intents if still needed by other parts)
    hw_bridge = MQTTBridge()
    hw_bridge.connect()

    # (RouterAgent is now replaced by CrewAI)

    # 3. Listen for TTS intents to send back to Mode 1
    bus.subscribe("tts_intent", send_tts_to_mode1)

    # 4. Start the internal utterance listener
    m2_client.on_connect = on_connect
    m2_client.on_message = on_message
    m2_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    m2_client.loop_start()

    print("\n=======================================")
    print(">>> MODE 2 BACKGROUND SERVER RUNNING <<<")
    print("Waiting for commands from Mode 1...")
    print("=======================================\n")

    # Keep the async loop alive forever
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down Mode 2...")
        m2_client.loop_stop()
        m2_client.disconnect()
