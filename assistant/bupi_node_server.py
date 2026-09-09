import sys
import os
import json
import time
import math
import sqlite3
import threading
import asyncio
import websockets
import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJECT_ROOT, "bupi_telemetry.db")

# -------------------------------------------------------------
# Global State & Locks
# -------------------------------------------------------------
connected_nodes = set()
ui_clients = set()
hardware_clients = set()
_loop = None

live_nodes = {}
live_nodes_lock = threading.Lock()

latest_telemetry = {
    "distance_cm": 150.0,
    "pir": 0,
    "pitch": 0.0,
    "roll": 0.0,
    "effective_tilt": 0.0,
    "heading": 0.0,
    "ax": 0.0, "ay": 0.0, "az": 1.0,
    "gx": 0.0, "gy": 0.0, "gz": 0.0,
    "updated_at": 0.0,
    "source": "none"
}
telem_lock = threading.Lock()

# Serial connection state
serial_port_obj = None
serial_lock = threading.Lock()
active_serial_port = None
serial_running = True

# MQTT connection
mqtt_client = None
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

# Rate limiting for DB writes (every 100ms max to prevent SQLite write lock contention)
last_db_write_time = 0.0

# -------------------------------------------------------------
# Node Presence Management
# -------------------------------------------------------------
def register_node(node_id, ip, conn_type, device="Unknown Device", capabilities=None, tasks=None):
    if capabilities is None:
        capabilities = []
    if tasks is None:
        tasks = []
    
    with live_nodes_lock:
        live_nodes[node_id] = {
            "id": node_id,
            "ip": ip,
            "type": conn_type,
            "device": device,
            "capabilities": capabilities,
            "tasks": tasks,
            "last_seen": time.time(),
            "status": "online"
        }
    broadcast_nodes()
    _persist_node_to_db(node_id, device, ip, capabilities, "ONLINE")

def update_node_heartbeat(node_id):
    with live_nodes_lock:
        if node_id in live_nodes:
            live_nodes[node_id]["last_seen"] = time.time()
            if live_nodes[node_id]["status"] != "online":
                live_nodes[node_id]["status"] = "online"
                broadcast_nodes()
                _persist_node_to_db(node_id, live_nodes[node_id].get("device", "ESP32 Node"), live_nodes[node_id].get("ip", ""), live_nodes[node_id].get("capabilities", []), "ONLINE")

def mark_node_offline(node_id):
    with live_nodes_lock:
        if node_id in live_nodes and live_nodes[node_id]["status"] != "offline":
            live_nodes[node_id]["status"] = "offline"
            broadcast_nodes()
            _persist_node_to_db(node_id, live_nodes[node_id].get("device", "ESP32 Node"), live_nodes[node_id].get("ip", ""), live_nodes[node_id].get("capabilities", []), "OFFLINE")

def check_node_timeouts():
    now = time.time()
    changed = False
    with live_nodes_lock:
        for node_id, node in live_nodes.items():
            if node["status"] == "online" and (now - node["last_seen"]) > 15:
                node["status"] = "offline"
                changed = True
                _persist_node_to_db(node_id, node.get("device", "ESP32 Node"), node.get("ip", ""), node.get("capabilities", []), "OFFLINE")
    if changed:
        broadcast_nodes()

def broadcast_nodes():
    with live_nodes_lock:
        nodes_list = list(live_nodes.values())
    print(json.dumps({"type": "connected_nodes", "value": nodes_list}), flush=True)

def _persist_node_to_db(client_id, device_name, ip_address, capabilities, status):
    try:
        caps_str = json.dumps(capabilities) if isinstance(capabilities, list) else str(capabilities)
        conn = sqlite3.connect(DB_PATH, timeout=2.0)
        c = conn.cursor()
        c.execute("""
            INSERT INTO nodes (client_id, device_name, ip_address, capabilities, last_heartbeat, status)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id) DO UPDATE SET
                device_name=excluded.device_name,
                ip_address=excluded.ip_address,
                capabilities=excluded.capabilities,
                last_heartbeat=excluded.last_heartbeat,
                status=excluded.status
        """, (client_id, device_name, ip_address, caps_str, time.time(), status))
        conn.commit()
        conn.close()
    except Exception:
        pass

# -------------------------------------------------------------
# Telemetry Ingestion & DB Storage
# -------------------------------------------------------------
def handle_incoming_telemetry(data: dict, source: str = "serial"):
    global latest_telemetry, last_db_write_time
    now = time.time()

    # Extract raw readings
    dist = float(data.get("distance_cm", data.get("distance", 150.0)))
    pir = int(data.get("pir", data.get("motion", 0)))
    pitch = float(data.get("pitch", 0.0))
    roll = float(data.get("roll", 0.0))
    heading = float(data.get("heading", data.get("yaw", 0.0)))
    ax = float(data.get("ax", 0.0))
    ay = float(data.get("ay", 0.0))
    az = float(data.get("az", 1.0))
    gx = float(data.get("gx", 0.0))
    gy = float(data.get("gy", 0.0))
    gz = float(data.get("gz", 0.0))

    # Inverted MPU6050 chassis compensation (resting roll ~ -170 deg)
    roll_abs = abs(roll)
    effective_roll = abs(180.0 - roll_abs) if roll_abs > 90.0 else roll_abs
    effective_pitch = abs(pitch)
    effective_tilt = max(effective_roll, effective_pitch)

    with telem_lock:
        latest_telemetry = {
            "distance_cm": dist,
            "pir": pir,
            "pitch": pitch,
            "roll": roll,
            "effective_tilt": effective_tilt,
            "heading": heading,
            "ax": ax, "ay": ay, "az": az,
            "gx": gx, "gy": gy, "gz": gz,
            "updated_at": now,
            "source": source
        }

    # Keep ESP32 node registered and marked online
    node_id = "ESP32_BUPI_ROBOT"
    device_name = f"BUPI Mobile Platform ({source.upper()})"
    ip_str = "USB" if source == "serial" else "WiFi"
    update_node_heartbeat(node_id)
    if node_id not in live_nodes:
        register_node(node_id, ip_str, source.capitalize(), device_name, ["differential_drive", "HC-SR04", "PIR", "MPU6050"], ["Robotic Navigation", "Sensing"])

    # Throttled SQLite persistence (max 10Hz to preserve SSD / DB write lock)
    if now - last_db_write_time >= 0.1:
        last_db_write_time = now
        try:
            conn = sqlite3.connect(DB_PATH, timeout=1.0)
            c = conn.cursor()
            rows = [
                (now, "distance", dist),
                (now, "pir", pir),
                (now, "pitch", effective_pitch),
                (now, "roll", effective_roll),
                (now, "tilt", effective_tilt),
                (now, "heading", heading)
            ]
            c.executemany("INSERT INTO telemetry (timestamp, sensor_id, value) VALUES (?, ?, ?)", rows)
            conn.commit()
            conn.close()
        except Exception:
            pass

    # Publish to MQTT for any external monitors
    if mqtt_client:
        try:
            mqtt_client.publish("bupi/sensors/distance/state", f"{dist:.1f}")
            mqtt_client.publish("bupi/sensors/pir/state", str(pir))
            mqtt_client.publish("bupi/sensors/imu/state", json.dumps({
                "heading": heading,
                "tilt": effective_tilt,
                "pitch": pitch,
                "roll": roll,
                "ax": ax, "ay": ay, "az": az
            }))
        except Exception:
            pass

    # Broadcast to connected UI WebSockets (Bupi Hub / bupi_autonomous.js)
    if _loop is not None and _loop.is_running() and connected_nodes:
        ui_payload = json.dumps({
            "type": "telemetry_update",
            "goal": {
                "raw_command": "Mode 2 Active",
                "intent": "HARDWARE_TELEMETRY",
                "goal_description": "ESP32 20Hz Perception Loop"
            },
            "state": {
                "mode": "ONLINE",
                "last_decision": "AUTONOMOUS_READY",
                "environment": {
                    "distance_cm": round(dist, 1),
                    "proximity_class": "collision_risk" if dist <= 15 else ("near" if dist <= 40 else "clear"),
                    "motion_detected": (pir == 1),
                    "tilt_deg": round(effective_tilt, 1),
                    "heading_deg": round(heading, 1)
                }
            },
            "epistemic_ladder": {
                "observation": f"Dist={dist:.1f}cm, PIR={pir}, Tilt={effective_tilt:.1f}°, Hdg={heading:.1f}°",
                "inference": "Obstacle barrier close!" if dist <= 15 else ("Clear forward corridor" if dist > 40 else "Warning corridor"),
                "decision": "READY"
            },
            "safe_action": {
                "action": "TELEMETRY_FLOW",
                "speed": 100
            },
            "arena": {
                "room": {"width_cm": 500, "height_cm": 400},
                "robot": {
                    "x": 100, "y": 200,
                    "heading_deg": round(heading, 1),
                    "ultrasonic_fov_deg": 25,
                    "pir_fov_deg": 100
                },
                "sensors": {
                    "raw_distance_cm": round(dist, 1),
                    "raw_pir": pir,
                    "ax": ax, "ay": ay, "az": az,
                    "heading": heading
                }
            }
        })
        # Broadcast to connected UI WebSockets (Bupi Hub / bupi_autonomous.js)
        target_ui = ui_clients if ui_clients else (connected_nodes - hardware_clients)
        for ws in list(target_ui):
            try:
                asyncio.run_coroutine_threadsafe(ws.send(ui_payload), _loop)
            except Exception:
                pass

def get_latest_telemetry():
    with telem_lock:
        return dict(latest_telemetry)

# -------------------------------------------------------------
# Dispatch Commands to Physical ESP32
# -------------------------------------------------------------
def dispatch_to_esp32(cmd_str: str) -> bool:
    """
    Sends a string command to the physical ESP32.
    Routes to WebSocket hardware clients if connected, and to USB Serial.
    NEVER sends raw motor commands to the browser UI.
    """
    cmd_clean = cmd_str.strip()
    if not cmd_clean:
        return False

    success = False
    
    # 1. Try USB Serial
    with serial_lock:
        if serial_port_obj and serial_port_obj.is_open:
            try:
                packet = (cmd_clean + "\n").encode('utf-8')
                serial_port_obj.write(packet)
                serial_port_obj.flush()
                print(f"[Hardware Bridge -> Serial TX] Sent: {cmd_clean}", flush=True)
                success = True
            except Exception as se:
                print(f"[Hardware Bridge] Serial write failed: {se}", flush=True)

    # 2. Try WebSocket hardware nodes (strictly hardware, never UI)
    if _loop is not None and _loop.is_running():
        for ws in list(hardware_clients):
            try:
                asyncio.run_coroutine_threadsafe(ws.send(cmd_clean), _loop)
                print(f"[Hardware Bridge -> WS TX] Dispatched to hardware node: {cmd_clean}", flush=True)
                success = True
            except Exception as we:
                print(f"[Hardware Bridge] WS write failed: {we}", flush=True)

    return success

def dispatch_motor_command(direction_or_json):
    """
    Dispatches motor movements ('forward', 'backward', 'left', 'right', 'stop', or JSON)
    to the ESP32.
    """
    if isinstance(direction_or_json, dict):
        cmd = json.dumps(direction_or_json)
    else:
        cmd = str(direction_or_json).strip()
    return dispatch_to_esp32(cmd)

# -------------------------------------------------------------
# USB Serial Background Supervisor
# -------------------------------------------------------------
def find_esp32_port():
    try:
        import serial.tools.list_ports as lp
        ports = list(lp.comports())
        
        # Priority 1: Check COM3 first (standard user ESP32 port)
        for p in ports:
            if p.device.upper() == "COM3":
                return p.device

        # Priority 2: CP210x or CH340 or Silicon Labs
        for p in ports:
            desc = p.description.lower()
            if "silicon labs" in desc or "cp210" in desc or "ch340" in desc or "usb-to-uart" in desc:
                return p.device

        # Priority 3: Any USB COM port
        for p in ports:
            if "USB" in p.description.upper():
                return p.device

    except Exception:
        pass
    return None

def serial_supervisor_thread():
    global serial_port_obj, active_serial_port, serial_running
    import serial

    print("[Hardware Bridge] Serial Supervisor Thread active.", flush=True)
    rx_buffer = ""

    while serial_running:
        if serial_port_obj is None or not serial_port_obj.is_open:
            port = find_esp32_port()
            if port:
                try:
                    ser = serial.Serial(port, 115200, timeout=0.1)
                    with serial_lock:
                        serial_port_obj = ser
                        active_serial_port = port
                    print(f"\n[Hardware Bridge] ✅ Connected to ESP32 on {port} @ 115200 baud!", flush=True)
                    register_node("ESP32_SERIAL", "COM3", "Serial", "BUPI Mobile Platform", ["differential_drive", "HC-SR04", "PIR", "MPU6050"], ["Robotic Navigation", "Sensing"])
                except Exception as e:
                    time.sleep(1.5)
                    continue
            else:
                time.sleep(2.0)
                continue

        # Connected: read loop
        try:
            if serial_port_obj and serial_port_obj.in_waiting > 0:
                chunk = serial_port_obj.read(serial_port_obj.in_waiting).decode('utf-8', errors='ignore')
                rx_buffer += chunk
                while '\n' in rx_buffer:
                    line, rx_buffer = rx_buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Check if line is telemetry JSON
                    if line.startswith('{') and line.endswith('}'):
                        try:
                            data = json.loads(line)
                            if "distance_cm" in data or "heading" in data or "pir" in data or "pitch" in data:
                                handle_incoming_telemetry(data, source="serial")
                                continue
                        except Exception:
                            pass
                    
                    # Print regular debug line
                    print(f"[ESP32 Serial] {line}", flush=True)
            else:
                time.sleep(0.01)

        except Exception as err:
            print(f"[Hardware Bridge] Serial connection lost on {active_serial_port}: {err}. Reconnecting in 2s...", flush=True)
            with serial_lock:
                if serial_port_obj:
                    try:
                        serial_port_obj.close()
                    except Exception:
                        pass
                    serial_port_obj = None
                    active_serial_port = None
            mark_node_offline("ESP32_SERIAL")
            time.sleep(2.0)

# -------------------------------------------------------------
# WebSocket Server Handler
# -------------------------------------------------------------
async def handle_connection(websocket):
    ip = websocket.remote_address[0]
    is_loopback = ip in ["127.0.0.1", "::1", "localhost"]
    
    connected_nodes.add(websocket)
    if is_loopback:
        ui_clients.add(websocket)
        print(f"[Hardware Bridge] New UI WebSocket connection from {ip}", flush=True)
    else:
        hardware_clients.add(websocket)
        print(f"[Hardware Bridge] New Hardware WebSocket connection from {ip}", flush=True)

    node_id = f"WS_{ip.replace('.', '_')}"

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                msg_type = data.get("type", "")

                # If this socket sends hardware telemetry or announces as a robot platform, mark as hardware
                if msg_type == "announce" or "distance_cm" in data or "heading" in data or "pir" in data:
                    if websocket in ui_clients:
                        ui_clients.discard(websocket)
                    hardware_clients.add(websocket)

                # 1. ESP32 Node Announcements & Heartbeats
                if msg_type == "announce":
                    register_node(
                        node_id,
                        ip,
                        "WebSocket",
                        data.get("device", "BUPI Mobile Platform"),
                        data.get("capabilities", ["Display", "Motors"]),
                        data.get("tasks", ["Robotic Control"])
                    )
                elif msg_type == "heartbeat":
                    update_node_heartbeat(node_id)

                # 2. ESP32 20Hz Telemetry
                elif "distance_cm" in data or "heading" in data or "pir" in data:
                    handle_incoming_telemetry(data, source="websocket")

                # 3. User Commands from Bupi Hub UI (bupi_autonomous.js)
                elif msg_type == "command":
                    user_cmd = data.get("text", "")
                    if user_cmd:
                        print(f"\n[Hardware Bridge] Received UI command: '{user_cmd}' -> Routing to Mode 2 Utterance!", flush=True)
                        if mqtt_client:
                            mqtt_client.publish("bupi/internal/utterance", json.dumps({"text": user_cmd}))

                # 4. Arena Simulation Drag Events
                elif msg_type in ["move_human", "move_obstacle", "inject_obstacle"]:
                    pass

            except Exception as e:
                # Raw text fallback
                update_node_heartbeat(node_id)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        print(f"[Hardware Bridge] WebSocket disconnected: {websocket.remote_address}", flush=True)
        connected_nodes.discard(websocket)
        ui_clients.discard(websocket)
        hardware_clients.discard(websocket)
        mark_node_offline(node_id)

# -------------------------------------------------------------
# MQTT Client Integration
# -------------------------------------------------------------
last_motor_dispatch_time = 0.0
last_motor_dispatch_cmd = ""

def on_mqtt_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[Hardware Bridge] Connected to Mosquitto MQTT ({MQTT_BROKER}:{MQTT_PORT}) code={reason_code}", flush=True)
    client.subscribe("bupi/actuators/motors/cmd")
    client.subscribe("bupi/actuators/motors/cmd/json")
    client.subscribe("bupi/actuators/lcd/cmd")
    client.subscribe("bupi/nodes/desk_display/cmd")
    client.subscribe("bupi/hardware/#")

def on_mqtt_message(client, userdata, msg):
    global last_motor_dispatch_time, last_motor_dispatch_cmd
    topic = msg.topic
    try:
        payload_str = msg.payload.decode('utf-8', errors='ignore')
    except Exception:
        payload_str = str(msg.payload)

    # 1. Motor commands from Mode 2 / hardware_tools / autonomous_goal_agent
    if topic in ["bupi/actuators/motors/cmd", "bupi/actuators/motors/cmd/json"]:
        now_ts = time.time()
        # Suppress rapid duplicate command bursts (<50ms)
        if (now_ts - last_motor_dispatch_time) < 0.05 and payload_str == last_motor_dispatch_cmd:
            return
        last_motor_dispatch_time = now_ts
        last_motor_dispatch_cmd = payload_str

        print(f"[Hardware Bridge <- MQTT Motor Cmd] {topic} -> '{payload_str}'", flush=True)
        dispatch_to_esp32(payload_str)

    # 2. LCD Display commands
    elif topic in ["bupi/actuators/lcd/cmd", "bupi/nodes/desk_display/cmd"]:
        print(f"[Hardware Bridge <- MQTT Display Cmd] '{payload_str}'", flush=True)
        display_payload = json.dumps({"action": "display", "text": payload_str[:32]})
        dispatch_to_esp32(display_payload)

    # 3. Hardware Relays
    elif topic.startswith("bupi/hardware/"):
        print(f"[Hardware Bridge <- MQTT Relay] {topic} -> '{payload_str}'", flush=True)
        dispatch_to_esp32(json.dumps({"topic": topic, "state": payload_str}))

def init_mqtt():
    global mqtt_client
    try:
        import random
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"BUPI_Hardware_Bridge_{random.randint(1000, 9999)}")
        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_message = on_mqtt_message
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"[Hardware Bridge Warning] MQTT connect error: {e}", flush=True)

# -------------------------------------------------------------
# Public API & Server Startup
# -------------------------------------------------------------
_message_override_until = 0

def send_to_esp32(title, message, duration=0):
    global _message_override_until
    if title == "Bupi Status:" and time.time() < _message_override_until:
        return
    if duration > 0:
        _message_override_until = time.time() + duration

    payload_text = f"{title} {message}".strip()
    if title == "Bupi Status:":
        payload_text = message
        
    dispatch_to_esp32(json.dumps({"title": title[:16], "message": message[:16]}))

async def _start_server():
    global _loop
    _loop = asyncio.get_running_loop()
    print("[Hardware Bridge] Starting WebSocket Server on 0.0.0.0:8767...", flush=True)
    server = await websockets.serve(handle_connection, "0.0.0.0", 8767)
    await asyncio.Future()  # Run forever

def start_node_server():
    """Starts the WebSocket server, USB Serial supervisor, and MQTT bridge in background threads."""
    # 1. Start MQTT
    init_mqtt()

    # 2. Start USB Serial Supervisor
    serial_t = threading.Thread(target=serial_supervisor_thread, daemon=True)
    serial_t.start()

    # 3. Start WebSocket Server
    def run_ws_loop():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_start_server())

    ws_t = threading.Thread(target=run_ws_loop, daemon=True)
    ws_t.start()

    print("[Hardware Bridge] Unified Bridge running (Serial + WebSockets + MQTT)!", flush=True)

if __name__ == "__main__":
    start_node_server()
    print("Bridge active. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping bridge...")
        serial_running = False
