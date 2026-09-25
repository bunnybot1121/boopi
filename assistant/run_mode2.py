import sys
import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

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
from agents.local_orchestrator import local_orchestrator
try:
    from agents.robotic_crew import run_robotic_task
except Exception:
    run_robotic_task = None

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
LISTEN_TOPIC = "bupi/internal/utterance"

hw_bridge = None
# Fixed client_id ensures Mosquitto automatically replaces any stale zombie sessions
m2_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="Mode2_Main_Worker")

def on_connect(client, userdata, flags, reason_code, properties):
    print(f"[Mode 2] Connected. Listening for utterances on {LISTEN_TOPIC}", flush=True)
    client.subscribe(LISTEN_TOPIC)

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
    
    # 0. Fast-Pass: Deterministic Autonomous Missions, E-Stop, or Direct Actuation (<5ms)
    try:
        from agents.router_agent import router
        fast = router.quick_regex_classify(text)
        if fast:
            itype = fast.get("type")
            payload = fast.get("payload", {})
            if itype == "autonomous_mission":
                from agents.autonomous_goal_agent import goal_agent
                mission_text = payload.get("mission", text)
                res = goal_agent.start_mission(mission_text)
                m2_client.publish("bupi/internal/tts", json.dumps({"text": res}))
                return
            elif itype == "abort_mission":
                from agents.autonomous_goal_agent import goal_agent
                res = goal_agent.stop_mission()
                m2_client.publish("bupi/internal/tts", json.dumps({"text": "Mission stopped. Motors halted."}))
                return
            elif itype == "edge_avoid_mode":
                enabled = payload.get("enabled", True)
                payload_json = json.dumps({"action": "auto_avoid", "enabled": enabled})
                m2_client.publish("bupi/actuators/motors/cmd/json", payload_json)
                speech = "Edge obstacle avoidance enabled. Navigating on ESP32." if enabled else "Obstacle avoidance disabled. Standby."
                m2_client.publish("bupi/internal/tts", json.dumps({"text": speech}))
                return
            elif itype == "mission_report_query":
                from agents.autonomous_goal_agent import goal_agent
                latest = goal_agent.get_latest_mission_report()
                if latest:
                    m_name = latest.get("mission_name", "Mission")
                    summary = latest.get("summary", "")
                    status = latest.get("status", "COMPLETED")
                    dur = latest.get("duration_seconds", 0)
                    spoken = f"Last mission {m_name} finished in {dur} seconds with status {status}. {summary}"
                else:
                    spoken = "No mission reports recorded yet. Say 'Boopi, find the human' to start a mission."
                m2_client.publish("bupi/internal/tts", json.dumps({"text": spoken}))
                return
            elif itype == "sensor_query":
                sensor_id = payload.get("sensor_id", "mq2")
                try:
                    from actions.hardware_tools import read_sensor_status
                    raw_fn = getattr(read_sensor_status, "func", read_sensor_status)
                    res_json = json.loads(raw_fn(sensor_id))
                    st = res_json.get("status", "OFFLINE")
                    val = res_json.get("raw_value")
                    bot_name = "Bot 2" if res_json.get("robot_id") == "bupi_02" else "Bot 1"

                    if sensor_id in ["distance", "ultrasonic", "hcsr04"]:
                        if st == "OFFLINE" or val is None:
                            spoken = "The ultrasonic distance sensor is currently offline. No live telemetry received from the robot."
                        elif val < 35.0:
                            spoken = f"Yes, an obstacle is detected {val:.1f} centimeters directly in front of {bot_name}."
                        else:
                            spoken = f"No obstacles detected. The path ahead is clear with {val:.1f} centimeters of clearance."
                    elif sensor_id in ["mq2", "gas", "smoke"]:
                        if st == "OFFLINE" or val is None:
                            spoken = "The MQ-2 gas sensor is currently offline. Please ensure Bot 2 is connected."
                        elif val > 300.0:
                            spoken = f"Warning! Elevated gas or smoke detected on Bot 2 at {val:.1f} ppm."
                        else:
                            spoken = f"Air quality is clean and safe. Gas level is {val:.1f} ppm."
                    elif sensor_id in ["temp", "temperature", "dht"]:
                        if st == "OFFLINE" or val is None:
                            spoken = "The temperature sensor is currently offline."
                        else:
                            spoken = f"The ambient temperature is {val:.1f} degrees Celsius, status is {st}."
                    elif sensor_id in ["humidity"]:
                        if st == "OFFLINE" or val is None:
                            spoken = "The humidity sensor is currently offline."
                        else:
                            spoken = f"The ambient humidity is {val:.1f} percent, status is {st}."
                    else:
                        spoken = f"The {sensor_id} reading is {val}, status is {st}."
                except Exception as e:
                    spoken = f"Could not read {sensor_id}: {e}"
                m2_client.publish("bupi/internal/tts", json.dumps({"text": spoken}))
                return
            elif itype == "world_state_query":
                try:
                    from core.safety_validator import get_current_world_state
                    ws = get_current_world_state()
                    gas_st = "offline" if ws.get("gas") in ["UNKNOWN_STALE", "OFFLINE", "UNKNOWN"] else ws.get("gas", "safe")
                    dist_st = "offline" if ws.get("distance") in ["UNKNOWN_STALE", "OFFLINE", "UNKNOWN"] else ws.get("distance", "clear")
                    spoken = f"World state: gas sensor is {gas_st}, front obstacle path is {dist_st}."
                except Exception as e:
                    spoken = f"World state check failed: {e}"
                m2_client.publish("bupi/internal/tts", json.dumps({"text": spoken}))
                return
            elif itype == "nodes_query":
                try:
                    from actions.hardware_tools import get_connected_nodes
                    raw_fn = getattr(get_connected_nodes, "func", get_connected_nodes)
                    res_json = json.loads(raw_fn())
                    online = [n for n in res_json.get("connected_nodes", []) if n.get("status") == "ONLINE"]
                    if online:
                        dev = online[0].get("device_name", "ESP32")
                        ip = online[0].get("ip_address", "")
                        ip_str = f" at IP {ip}" if ip and ip != "unknown" else ""
                        spoken = f"Yes! An ESP32 is online and connected. {dev}{ip_str}."
                    else:
                        spoken = "No ESP32 nodes are currently connected on the network."
                except Exception as e:
                    spoken = f"Node query failed: {e}"
            elif itype == "hardware_intent":
                dev = payload.get("device")
                action = payload.get("action")
                direction = payload.get("direction", "")
                if dev == "motors":
                    from actions.hardware_tools import control_motors
                    fn = getattr(control_motors, "func", getattr(control_motors, "_run", control_motors))
                    target_bot = payload.get("robot_id") or "bupi_01"
                    fn(direction=direction, robot_id=target_bot)
                    bot_label = "both bots" if target_bot in ["all", "both", "fleet"] else target_bot
                    speech = "Emergency stop triggered. Motors halted." if direction == "stop" else f"Driving {direction} ({bot_label})."
                    m2_client.publish("bupi/internal/tts", json.dumps({"text": speech}))
                    return
                elif dev == "relay":
                    from actions.hardware_tools import control_relay
                    fn = getattr(control_relay, "func", getattr(control_relay, "_run", control_relay))
                    fn("relay_1", "turn_on" if action == "ON" else "turn_off")
                    m2_client.publish("bupi/internal/tts", json.dumps({"text": f"Relay turned {action.lower()}."}))
                    return
    except Exception as fp_err:
        print(f"[Mode 2 Fast-Pass Error] {fp_err}", flush=True)

    # 1. Primary: Run fast local single-agent orchestrator (<500ms offline on RTX 4050)
    try:
        print(f"\n--- [ROBOT] EXECUTING LOCAL OFFLINE ORCHESTRATOR ---", flush=True)
        response = local_orchestrator.run_task(text)
        print(f"--- [ROBOT] LOCAL ORCHESTRATOR FINISHED ---", flush=True)
        print(f"Result: {response}", flush=True)
        m2_client.publish("bupi/internal/tts", json.dumps({"text": response}))
        return
    except Exception as local_err:
        print(f"[Mode 2] Local Orchestrator error: {local_err}. Trying fallback...", flush=True)

    # 2. Fallback: CrewAI (if available and configured)
    if run_robotic_task:
        max_retries = 2
        import time
        for attempt in range(max_retries):
            try:
                print(f"\n--- [ROBOT] KICKING OFF CREW AI FALLBACK (Attempt {attempt + 1}) ---", flush=True)
                response = run_robotic_task(text)
                print(f"--- [ROBOT] CREW AI FINISHED ---", flush=True)
                print(f"Result: {response}", flush=True)
                m2_client.publish("bupi/internal/tts", json.dumps({"text": response}))
                return
            except Exception as e:
                print(f"[Mode 2] CrewAI Attempt {attempt + 1} Error: {e}", flush=True)
                if attempt < max_retries - 1:
                    time.sleep(3)
    
    m2_client.publish("bupi/internal/tts", json.dumps({"text": "Sorry, my robotic orchestrator encountered an error executing that action."}))

# Catch the TTS intent from the RouterAgent and push it back to Mode 1
async def send_tts_to_mode1(payload):
    text = payload.get("text", "")
    if text:
        print(f"[Mode 2] Sending TTS back to Mode 1: '{text}'", flush=True)
        m2_client.publish("bupi/internal/tts", json.dumps({"text": text}))

async def main():
    global loop
    loop = asyncio.get_running_loop()

    # 0. Ensure Hardware Bridge is active (WebSocket port 8767, USB Serial, and MQTT)
    try:
        from bupi_node_server import start_node_server
        start_node_server()
    except Exception as nse:
        print(f"[Mode 2 Warning] Could not start node server: {nse}", flush=True)

    global hw_bridge
    # 1. Start the MQTT Bridge (handles any raw hardware intents if still needed by other parts)
    hw_bridge = MQTTBridge()
    hw_bridge.connect()
    try:
        import actions.hardware_tools as _hw_tools
        _hw_tools.active_bridge = hw_bridge
    except Exception:
        pass

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
    # Terminate any prior stale run_mode2 instance to guarantee strict singleton execution
    PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mode2.pid")
    try:
        curr_pid = os.getpid()
        parent_pid = os.getppid() if hasattr(os, "getppid") else -1
        if os.path.exists(PID_FILE):
            with open(PID_FILE, "r") as pf:
                old_pid = int(pf.read().strip())
            if old_pid > 0 and old_pid != curr_pid and old_pid != parent_pid:
                try:
                    import subprocess
                    out = subprocess.check_output(f'powershell -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \\"ProcessId = {old_pid}\\").CommandLine"', shell=True).decode()
                    if "run_mode2.py" in out:
                        import signal
                        os.kill(old_pid, signal.SIGTERM)
                except Exception:
                    pass
        with open(PID_FILE, "w") as pf:
            pf.write(str(curr_pid))
    except Exception:
        pass

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down Mode 2...")
        m2_client.loop_stop()
        m2_client.disconnect()
