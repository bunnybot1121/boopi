import sys
import os
import json
import time
import math
import sqlite3
import threading
import asyncio
import websockets
import queue
import subprocess
import logging
import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish
from typing import Optional, Dict, Any, List, Union, Tuple

logging.getLogger("websockets.server").setLevel(logging.ERROR)
logging.getLogger("websockets.protocol").setLevel(logging.ERROR)

try:
    from core.kinematics_odometry import odometry_engine
except ImportError:
    odometry_engine = None

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJECT_ROOT, "bupi_telemetry.db")

# Asynchronous DB write queue to eliminate disk fsync latency from WS loop
_db_queue = queue.Queue(maxsize=2000)

def _db_writer_worker():
    """Background worker: batches telemetry DB writes every 1.5s, eliminating disk fsync latency from WS loop."""
    while True:
        try:
            batch = []
            try:
                item = _db_queue.get(timeout=1.5)
                batch.append(item)
                while not _db_queue.empty() and len(batch) < 300:
                    batch.append(_db_queue.get_nowait())
            except queue.Empty:
                pass

            if batch:
                conn = sqlite3.connect(DB_PATH, timeout=2.0)
                c = conn.cursor()
                c.executemany("INSERT INTO telemetry (timestamp, sensor_id, value) VALUES (?, ?, ?)", batch)
                conn.commit()
                conn.close()
        except Exception:
            pass

# -------------------------------------------------------------
# Global State & Locks
# -------------------------------------------------------------
connected_nodes = set()
ui_clients = set()
hardware_clients = set()
hardware_clients_by_bot = {}  # Maps bot_id ("bupi_01", "bupi_02") -> websocket client
_loop = None

live_nodes = {}
live_nodes_lock = threading.Lock()

telemetry_by_bot = {
    "bupi_01": {
        "bot_id": "bupi_01",
        "robot_id": "bupi_01",
        "distance_cm": 200.0,
        "pir": 0,
        "pitch": 0.0,
        "roll": 0.0,
        "effective_tilt": 0.0,
        "heading": 0.0,
        "ax": 0.0, "ay": 0.0, "az": 1.0,
        "gx": 0.0, "gy": 0.0, "gz": 0.0,
        "gas_ppm": 0.0,
        "temp_c": 25.0,
        "temperature_c": 25.0,
        "humidity": 50.0,
        "steps": 0,
        "dist_m": 0.0,
        "wifi_rssi": 0,
        "updated_at": 0.0,
        "source": "none"
    },
    "bupi_02": {
        "bot_id": "bupi_02",
        "robot_id": "bupi_02",
        "distance_cm": 200.0,
        "pir": 0,
        "pitch": 0.0,
        "roll": 0.0,
        "effective_tilt": 0.0,
        "heading": 0.0,
        "ax": 0.0, "ay": 0.0, "az": 1.0,
        "gx": 0.0, "gy": 0.0, "gz": 0.0,
        "gas_ppm": 35.0,
        "mq2_raw": 35.0,
        "temp_c": 24.5,
        "temperature_c": 24.5,
        "humidity": 50.0,
        "steps": 0,
        "dist_m": 0.0,
        "wifi_rssi": 0,
        "updated_at": 0.0,
        "source": "none"
    }
}
latest_telemetry = dict(telemetry_by_bot["bupi_01"])
telem_lock = threading.Lock()

# Multi-robot 2D Arena simulation & spatial state
arena_state = {
    "room": {"width_cm": 500, "height_cm": 400},
    "humans": [{"id": "person_1", "x": 340, "y": 180}],
    "obstacles": [{"id": "box_1", "x": 220, "y": 90, "width": 45, "height": 45}],
    "robots": {
        "bupi_01": {"x": 100, "y": 180, "heading": 0.0},
        "bupi_02": {"x": 100, "y": 280, "heading": 0.0}
    }
}
arena_lock = threading.Lock()

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
def handle_incoming_telemetry(data: dict, source: str = "serial", ws=None):
    global latest_telemetry, last_db_write_time
    now = time.time()

    # Identify bot_id
    bot_id = data.get("bot_id")
    if not bot_id:
        dev_str = str(data.get("device", "")).lower()
        if "bupi_02" in dev_str or "specialist" in dev_str or "environmental" in dev_str or "bot2" in dev_str:
            bot_id = "bupi_02"
        else:
            bot_id = "bupi_01"

    if ws is not None:
        hardware_clients_by_bot[bot_id] = ws

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
    mq2_val = float(data.get("gas_ppm", data.get("gas", data.get("mq2_raw", data.get("mq2", data.get("value", 0.0))))))
    temp_val = float(data.get("temp_c", data.get("temperature_c", data.get("temp", 25.0))))
    hum_val = float(data.get("humidity", data.get("humidity_pct", 50.0)))

    # Inverted MPU6050 chassis compensation (resting roll ~ -170 deg)
    roll_abs = abs(roll)
    effective_roll = abs(180.0 - roll_abs) if roll_abs > 90.0 else roll_abs
    effective_pitch = abs(pitch)
    effective_tilt = max(effective_roll, effective_pitch)

    # Extract steps, distance traveled, and Wi-Fi RSSI
    steps_raw = int(data.get("steps", data.get("step_count", 0)))
    dist_m_raw = float(data.get("dist_m", data.get("distance_traveled_m", 0.0)))
    wifi_rssi_raw = int(data.get("wifi_rssi", data.get("rssi", 0)))
    is_moving = bool(data.get("moving") == True or str(data.get("moving", "")).lower() == "true")

    # Update Kinematics Odometry & Wi-Fi distance engine
    dist_from_laptop = None
    prox_trend = "STATIONARY"
    prox_zone = "UNKNOWN"
    odo_x = 0.0
    odo_y = 0.0
    total_dist_m = dist_m_raw
    step_count = steps_raw

    if odometry_engine:
        if wifi_rssi_raw != 0:
            odometry_engine.update_wifi(bot_id, wifi_rssi_raw)
        odometry_engine.update_imu(bot_id, ax, ay, az, heading, dt=0.05, is_moving=is_moving, firmware_steps=steps_raw if steps_raw > 0 else None)
        odo_state = odometry_engine.get_state(bot_id)
        dist_from_laptop = odo_state.get("distance_from_laptop_m")
        prox_trend = odo_state.get("proximity_trend", "STATIONARY")
        prox_zone = odo_state.get("proximity_zone", "UNKNOWN")
        odo_x = odo_state.get("x_m", 0.0)
        odo_y = odo_state.get("y_m", 0.0)
        total_dist_m = odo_state.get("total_distance_m", dist_m_raw)
        step_count = odo_state.get("step_count", steps_raw)

    bot_telem = {
        "bot_id": bot_id,
        "robot_id": bot_id,
        "distance_cm": dist,
        "pir": pir,
        "pitch": pitch,
        "roll": roll,
        "effective_tilt": effective_tilt,
        "heading": heading,
        "ax": ax, "ay": ay, "az": az,
        "gx": gx, "gy": gy, "gz": gz,
        "gas_ppm": mq2_val,
        "mq2_raw": mq2_val,
        "temp_c": temp_val,
        "temperature_c": temp_val,
        "humidity": hum_val,
        "steps": step_count,
        "step_count": step_count,
        "dist_m": total_dist_m,
        "total_distance_m": total_dist_m,
        "x_m": odo_x,
        "y_m": odo_y,
        "wifi_rssi": wifi_rssi_raw,
        "distance_from_laptop_m": dist_from_laptop,
        "proximity_trend": prox_trend,
        "proximity_zone": prox_zone,
        "updated_at": now,
        "source": source
    }

    with telem_lock:
        prev_telem = telemetry_by_bot.get(bot_id, {})
        last_pir_time = prev_telem.get("last_pir_time", 0.0)
        if pir == 1:
            last_pir_time = now
        bot_telem["last_pir_time"] = last_pir_time
        bot_telem["recent_pir"] = 1 if (now - last_pir_time < 30.0) else 0

        telemetry_by_bot[bot_id] = bot_telem
        latest_telemetry.update(bot_telem)

    # Keep ESP32 node registered and marked online
    node_id = f"ESP32_{bot_id.upper()}"
    device_name = f"BUPI {bot_id.upper()} ({source.upper()})"
    ip_str = "USB" if source == "serial" else "WiFi"
    update_node_heartbeat(node_id)
    if node_id not in live_nodes:
        caps = ["differential_drive", "HC-SR04", "MPU6050"]
        if bot_id == "bupi_01":
            caps.append("PIR")
        else:
            caps.extend(["MQ-2", "DHT22"])
        register_node(node_id, ip_str, source.capitalize(), device_name, caps, ["Robotic Navigation", "Sensing"])

    # Asynchronous Batched SQLite persistence (zero disk stall on network event loop)
    rows = [
        (now, f"{bot_id}_distance", dist),
        (now, f"{bot_id}_pir", pir),
        (now, f"{bot_id}_pitch", effective_pitch),
        (now, f"{bot_id}_roll", effective_roll),
        (now, f"{bot_id}_tilt", effective_tilt),
        (now, f"{bot_id}_heading", heading)
    ]
    if mq2_val > 0:
        rows.append((now, f"{bot_id}_mq2", mq2_val))
    if temp_val > 0:
        rows.append((now, f"{bot_id}_temp", temp_val))
        rows.append((now, f"{bot_id}_temperature", temp_val))
    if hum_val > 0:
        rows.append((now, f"{bot_id}_humidity", hum_val))
    
    if _db_queue.qsize() < 1800:
        for r in rows:
            _db_queue.put_nowait(r)

    # Publish to MQTT for external monitors (both namespaced and default topics)
    if mqtt_client:
        try:
            mqtt_client.publish(f"bupi/{bot_id}/sensors/distance/state", f"{dist:.1f}")
            mqtt_client.publish(f"bupi/{bot_id}/sensors/pir/state", str(pir))
            mqtt_client.publish(f"bupi/{bot_id}/sensors/imu/state", json.dumps({
                "heading": heading,
                "tilt": effective_tilt,
                "pitch": pitch,
                "roll": roll,
                "ax": ax, "ay": ay, "az": az
            }))
            if mq2_val > 0:
                mqtt_client.publish(f"bupi/{bot_id}/sensors/mq2/state", str(mq2_val))
                mqtt_client.publish("bupi/sensors/mq2/state", str(mq2_val))
            if temp_val > 0:
                mqtt_client.publish(f"bupi/{bot_id}/sensors/temp/state", f"{temp_val:.1f}")
                mqtt_client.publish("bupi/sensors/dht/temperature", f"{temp_val:.1f}")
            if hum_val > 0:
                mqtt_client.publish(f"bupi/{bot_id}/sensors/humidity/state", f"{hum_val:.1f}")
                mqtt_client.publish("bupi/sensors/dht/humidity", f"{hum_val:.1f}")
            if bot_id == "bupi_01":
                mqtt_client.publish("bupi/sensors/distance/state", f"{dist:.1f}")
                mqtt_client.publish("bupi/sensors/pir/state", str(pir))
        except Exception:
            pass

    # Update robot heading and simulated movement in 2D arena
    with arena_lock:
        if bot_id not in arena_state["robots"]:
            arena_state["robots"][bot_id] = {
                "x": 100 if bot_id == "bupi_01" else 180,
                "y": 180 if bot_id == "bupi_01" else 260,
                "heading": 0.0
            }
        arena_state["robots"][bot_id]["heading"] = heading

        # If robot reports movement, advance slightly in heading direction for live visualization
        if data.get("moving") is True or str(data.get("moving")).lower() == "true":
            rad = math.radians(heading)
            arena_state["robots"][bot_id]["x"] = max(30, min(470, arena_state["robots"][bot_id]["x"] + math.cos(rad) * 4.0))
            arena_state["robots"][bot_id]["y"] = max(30, min(370, arena_state["robots"][bot_id]["y"] + math.sin(rad) * 4.0))

        # Build fleet state representation for dual-bot 2D canvas
        fleet_dict = {}
        for b_id in ["bupi_01", "bupi_02"]:
            b_telem = telemetry_by_bot.get(b_id, {})
            pos = arena_state["robots"].get(b_id, {"x": 100 if b_id == "bupi_01" else 180, "y": 180 if b_id == "bupi_01" else 260, "heading": 0.0})
            fleet_dict[b_id] = {
                "bot_id": b_id,
                "role": "SCOUT" if b_id == "bupi_01" else "ENVIRONMENTAL",
                "x": pos["x"],
                "y": pos["y"],
                "heading_deg": round(b_telem.get("heading", pos.get("heading", 0.0)), 1),
                "ultrasonic_fov_deg": 25,
                "pir_fov_deg": 100 if b_id == "bupi_01" else 0,
                "distance_cm": round(b_telem.get("distance_cm", 150.0), 1),
                "pir": b_telem.get("pir", 0),
                "gas_ppm": round(b_telem.get("gas_ppm", 0.0), 1),
                "temp_c": round(b_telem.get("temp_c", 25.0), 1),
                "is_active": (now - b_telem.get("updated_at", 0)) < 10.0
            }

    # Broadcast to connected UI WebSockets (Bupi Hub / bupi_autonomous.js)
    if _loop is not None and _loop.is_running() and connected_nodes:
        ui_payload = build_ui_telemetry_payload(bot_id)
        target_ui = ui_clients if ui_clients else (connected_nodes - hardware_clients)
        for ws_client in list(target_ui):
            try:
                asyncio.run_coroutine_threadsafe(ws_client.send(ui_payload), _loop)
            except Exception:
                pass

def build_ui_telemetry_payload(bot_id: str = "bupi_01") -> str:
    now = time.time()
    with telem_lock:
        b_telem = telemetry_by_bot.get(bot_id, latest_telemetry)
        dist = float(b_telem.get("distance_cm", 200.0))
        pir = int(b_telem.get("pir", 0))
        heading = float(b_telem.get("heading", 0.0))
        effective_tilt = float(b_telem.get("tilt", 0.0))
        mq2_val = float(b_telem.get("gas_ppm", 35.0))
        temp_val = float(b_telem.get("temp_c", 24.5))
        hum_val = float(b_telem.get("humidity", 50.0))
        ax = float(b_telem.get("ax", 0.0))
        ay = float(b_telem.get("ay", 0.0))
        az = float(b_telem.get("az", 1.0))
        is_hw_active = (now - b_telem.get("updated_at", 0)) < 5.0

    with arena_lock:
        fleet_dict = {}
        for b_id in ["bupi_01", "bupi_02"]:
            bt = telemetry_by_bot.get(b_id, {})
            pos = arena_state["robots"].get(b_id, {
                "x": 120 if b_id == "bupi_01" else 180,
                "y": 180 if b_id == "bupi_01" else 260,
                "heading": 0.0
            })
            fleet_dict[b_id] = {
                "bot_id": b_id,
                "role": "SCOUT" if b_id == "bupi_01" else "ENVIRONMENTAL",
                "x": pos.get("x", 120),
                "y": pos.get("y", 180),
                "heading_deg": round(bt.get("heading", pos.get("heading", 0.0)), 1),
                "ultrasonic_fov_deg": 25,
                "pir_fov_deg": 100 if b_id == "bupi_01" else 0,
                "distance_cm": round(bt.get("distance_cm", 150.0), 1),
                "pir": bt.get("pir", 0),
                "gas_ppm": round(bt.get("gas_ppm", 35.0), 1),
                "temp_c": round(bt.get("temp_c", 24.5), 1),
                "is_active": (now - bt.get("updated_at", 0)) < 10.0
            }

        return json.dumps({
            "type": "telemetry_update",
            "bot_id": bot_id,
            "hardware_connected": is_hw_active,
            "goal": {
                "raw_command": f"Mode 2 Active ({bot_id})",
                "intent": "HARDWARE_PERCEPTION",
                "goal_description": f"ESP32 {bot_id} 20Hz Perception Loop"
            },
            "state": {
                "mode": "ONLINE" if is_hw_active else "ONLINE (Awaiting Telemetry)",
                "last_decision": "SAFETY_STOP" if dist <= 15.0 else ("ADVANCE_SEARCH" if dist > 40.0 else "SLOW_APPROACH"),
                "environment": {
                    "distance_cm": round(dist, 1),
                    "proximity_class": "collision_risk" if dist <= 15.0 else ("near" if dist <= 40.0 else "clear"),
                    "motion_detected": (pir == 1),
                    "tilt_deg": round(effective_tilt, 1),
                    "heading_deg": round(heading, 1),
                    "mq2_raw": mq2_val,
                    "temp_c": temp_val,
                    "humidity": hum_val
                }
            },
            "epistemic_ladder": {
                "observation": f"[{bot_id}] Dist={dist:.1f}cm, PIR={pir}, Gas={mq2_val:.1f}ppm, Tilt={effective_tilt:.1f}°, Hdg={heading:.1f}°",
                "inference": "Obstacle barrier close!" if dist <= 15.0 else ("Clear forward corridor" if dist > 40.0 else "Warning corridor"),
                "decision": "SAFETY_STOP" if dist <= 15.0 else ("ADVANCE" if dist > 40.0 else "SLOW_DOWN")
            },
            "safety_status": {
                "verdict": "OVERRIDDEN_FORCED_STOP" if dist <= 15.0 else ("MODIFIED" if dist <= 25.0 else "SAFE"),
                "status_message": "Proximity cutoff (<15cm) active" if dist <= 15.0 else "Safety supervisor nominal",
                "total_overrides": 1 if dist <= 15.0 else 0
            },
            "safe_action": {
                "action": "STOP" if dist <= 15.0 else ("MOVE_FORWARD" if dist > 40.0 else "EVADE"),
                "speed": 0 if dist <= 15.0 else (60 if dist > 40.0 else 30)
            },
            "arena": {
                "room": arena_state["room"],
                "humans": arena_state["humans"],
                "obstacles": arena_state["obstacles"],
                "robot": fleet_dict.get(bot_id, {
                    "bot_id": bot_id,
                    "x": 120, "y": 180,
                    "heading_deg": round(heading, 1),
                    "ultrasonic_fov_deg": 25,
                    "pir_fov_deg": 100
                }),
                "fleet": fleet_dict,
                "sensors": {
                    "raw_distance_cm": round(dist, 1),
                    "raw_pir": pir,
                    "ax": ax, "ay": ay, "az": az,
                    "heading": heading,
                    "mq2": mq2_val
                }
            }
        })

def _normalize_bot_id(bot_id: Optional[str]) -> Optional[str]:
    if not bot_id:
        return None
    s = str(bot_id).strip().lower()
    if s in ["bot2", "bot 2", "bupi2", "bupi_02", "bupi02", "specialist", "hazard bot"]:
        return "bupi_02"
    if s in ["bot1", "bot 1", "bupi1", "bupi_01", "bupi01", "scout"]:
        return "bupi_01"
    if s in ["all", "both", "fleet", "swarm"]:
        return "all"
    return s

def get_latest_telemetry(bot_id: Optional[str] = None):
    norm_id = _normalize_bot_id(bot_id) if bot_id else None
    with telem_lock:
        if norm_id and norm_id in telemetry_by_bot:
            return dict(telemetry_by_bot[norm_id])
        if bot_id and bot_id in telemetry_by_bot:
            return dict(telemetry_by_bot[bot_id])
        return dict(latest_telemetry)

# -------------------------------------------------------------
# Dispatch Commands to Physical ESP32
# -------------------------------------------------------------

def dispatch_to_esp32(cmd_str: str, target_bot_id: Optional[str] = None) -> bool:
    """
    Sends a string or JSON command to the physical ESP32.
    Routes to WebSocket hardware clients if connected, and to USB Serial.
    Can be targeted to a specific robot ('bupi_01' vs 'bupi_02').
    NEVER sends raw motor commands to the browser UI.
    """
    cmd_clean = cmd_str.strip()
    if not cmd_clean:
        return False

    norm_target = _normalize_bot_id(target_bot_id)

    # If payload is JSON, ensure target_bot is normalized in the JSON
    cmd_payload = cmd_clean
    try:
        parsed = json.loads(cmd_clean)
        if isinstance(parsed, dict):
            if not norm_target:
                norm_target = _normalize_bot_id(parsed.get("bot_id") or parsed.get("robot_id"))
            if norm_target and norm_target != "all":
                parsed["bot_id"] = norm_target
                parsed["robot_id"] = norm_target
                cmd_payload = json.dumps(parsed)
    except Exception:
        # If it's a plain string like "forward", "reverse", "left", "right", "stop"
        # and norm_target is specific (e.g. bupi_02), wrap it into a structured JSON
        # so the targeted bot receives it and other bots filter it out
        if norm_target in ["bupi_01", "bupi_02"]:
            cmd_payload = json.dumps({
                "action": cmd_clean,
                "speed": 255,
                "bot_id": norm_target,
                "robot_id": norm_target
            })

    success = False
    
    # 1. Try USB Serial (routes to bupi_01, bupi_02 or broadcast)
    with serial_lock:
        if serial_port_obj and serial_port_obj.is_open:
            try:
                packet = (cmd_payload + "\n").encode('utf-8')
                serial_port_obj.write(packet)
                serial_port_obj.flush()
                print(f"[Hardware Bridge -> Serial TX ({norm_target or 'all'})] Sent: {cmd_payload}", flush=True)
                success = True
            except Exception as se:
                print(f"[Hardware Bridge] Serial write failed: {se}", flush=True)

    # 2. Try WebSocket hardware nodes (targeted if target_bot_id is provided)
    if _loop is not None and _loop.is_running():
        if norm_target in ["all", "both", "fleet", "swarm", None]:
            # Broadcast to all connected hardware bots
            for ws in list(hardware_clients):
                try:
                    asyncio.run_coroutine_threadsafe(ws.send(cmd_payload), _loop)
                    print(f"[Hardware Bridge -> WS Broadcast] Dispatched: {cmd_payload}", flush=True)
                    success = True
                except Exception as we:
                    print(f"[Hardware Bridge] WS broadcast failed: {we}", flush=True)
        else:
            # Check targeted bot map with alias resolution
            target_ws = hardware_clients_by_bot.get(norm_target)
            if not target_ws:
                for k, sock in hardware_clients_by_bot.items():
                    if _normalize_bot_id(k) == norm_target:
                        target_ws = sock
                        break

            if target_ws and target_ws in hardware_clients:
                try:
                    asyncio.run_coroutine_threadsafe(target_ws.send(cmd_payload), _loop)
                    print(f"[Hardware Bridge -> WS TX ({norm_target})] Dispatched: {cmd_payload}", flush=True)
                    success = True
                except Exception as we:
                    print(f"[Hardware Bridge] WS write to {norm_target} failed: {we}", flush=True)
            else:
                # Fallback if specific bot socket not yet registered:
                # Dispatch wrapped JSON with bot_id so the intended robot accepts it and other ignores
                for ws in list(hardware_clients):
                    try:
                        asyncio.run_coroutine_threadsafe(ws.send(cmd_payload), _loop)
                        print(f"[Hardware Bridge -> WS TX (Targeted {norm_target})] Dispatched: {cmd_payload}", flush=True)
                        success = True
                    except Exception as we:
                        print(f"[Hardware Bridge] WS write failed: {we}", flush=True)

    return success

def dispatch_motor_command(direction_or_json, target_bot_id: Optional[str] = None):
    """
    Dispatches motor movements ('forward', 'backward', 'left', 'right', 'stop', or JSON)
    to the ESP32.
    """
    if isinstance(direction_or_json, dict):
        if not target_bot_id and "bot_id" in direction_or_json:
            target_bot_id = direction_or_json.get("bot_id")
        cmd = json.dumps(direction_or_json)
    else:
        cmd = str(direction_or_json).strip()
    return dispatch_to_esp32(cmd, target_bot_id=target_bot_id)

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
                    ser = serial.Serial(port, 115200, timeout=0.1, write_timeout=0.2)
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
        # Immediately push initial telemetry and arena snapshot to newly connected UI
        try:
            init_pkt = build_ui_telemetry_payload("bupi_01")
            await websocket.send(init_pkt)
        except Exception as e:
            pass
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
                if msg_type == "announce" or "distance_cm" in data or "heading" in data or "pir" in data or "flame" in data or "gas_ppm" in data:
                    if websocket in ui_clients:
                        ui_clients.discard(websocket)
                    hardware_clients.add(websocket)
                    bot_id_claimed = data.get("bot_id") or data.get("robot_id")
                    if bot_id_claimed:
                        hardware_clients_by_bot[bot_id_claimed] = websocket
                        norm_b = _normalize_bot_id(bot_id_claimed)
                        if norm_b:
                            hardware_clients_by_bot[norm_b] = websocket

                # 1. ESP32 Node Announcements & Heartbeats
                if msg_type == "announce":
                    bot_id = data.get("bot_id") or data.get("robot_id") or node_id
                    register_node(
                        bot_id,
                        ip,
                        "WebSocket",
                        data.get("device", "BUPI Mobile Platform"),
                        data.get("capabilities", ["Display", "Motors"]),
                        data.get("tasks", ["Robotic Control"])
                    )
                elif msg_type == "heartbeat":
                    update_node_heartbeat(node_id)

                # 2. ESP32 20Hz Telemetry
                elif "distance_cm" in data or "heading" in data or "pir" in data or "gas_ppm" in data:
                    handle_incoming_telemetry(data, source="websocket", ws=websocket)

                # 3. User Commands from Bupi Hub UI (bupi_autonomous.js)
                elif msg_type == "command":
                    user_cmd = data.get("text", "")
                    if user_cmd:
                        print(f"\n[Hardware Bridge] Received UI command: '{user_cmd}' -> Routing to Mode 2 Utterance!", flush=True)
                        if mqtt_client:
                            mqtt_client.publish("bupi/internal/utterance", json.dumps({"text": user_cmd}))

                # 4. Arena Simulation Drag Events
                elif msg_type == "move_human":
                    with arena_lock:
                        for h in arena_state["humans"]:
                            if h.get("id") == data.get("id"):
                                h["x"] = float(data.get("x", h["x"]))
                                h["y"] = float(data.get("y", h["y"]))
                elif msg_type == "move_obstacle":
                    with arena_lock:
                        for o in arena_state["obstacles"]:
                            if o.get("id") == data.get("id"):
                                o["x"] = float(data.get("x", o["x"]))
                                o["y"] = float(data.get("y", o["y"]))
                elif msg_type == "inject_obstacle":
                    with arena_lock:
                        arena_state["obstacles"].append({
                            "id": f"box_{len(arena_state['obstacles']) + 1}",
                            "x": float(data.get("x", 240)),
                            "y": float(data.get("y", 190)),
                            "width": 40,
                            "height": 40
                        })

            except Exception as e:
                # Raw text fallback
                update_node_heartbeat(node_id)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if not is_loopback:
            print(f"[Hardware Bridge] WebSocket disconnected: {websocket.remote_address}", flush=True)
        connected_nodes.discard(websocket)
        ui_clients.discard(websocket)
        hardware_clients.discard(websocket)
        for b_id, sock in list(hardware_clients_by_bot.items()):
            if sock == websocket:
                del hardware_clients_by_bot[b_id]
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
    client.subscribe("bupi/v1/bot1/actuators/motors/cmd")
    client.subscribe("bupi/v1/bot1/actuators/motors/cmd/json")
    client.subscribe("bupi/v1/bot2/actuators/motors/cmd")
    client.subscribe("bupi/v1/bot2/actuators/motors/cmd/json")
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
    if topic in ["bupi/actuators/motors/cmd", "bupi/actuators/motors/cmd/json", "bupi/v1/bot1/actuators/motors/cmd/json", "bupi/v1/bot2/actuators/motors/cmd/json"] or "actuators/motors/cmd" in topic:
        now_ts = time.time()
        # Suppress rapid duplicate command bursts (<50ms)
        if (now_ts - last_motor_dispatch_time) < 0.05 and payload_str == last_motor_dispatch_cmd:
            return
        last_motor_dispatch_time = now_ts
        last_motor_dispatch_cmd = payload_str

        # Resolve targeted robot
        target_bot_id = None
        if "bot2" in topic or "bupi_02" in topic:
            target_bot_id = "bupi_02"
        elif "bot1" in topic or "bupi_01" in topic:
            target_bot_id = "bupi_01"

        try:
            pdata = json.loads(payload_str)
            if isinstance(pdata, dict) and (pdata.get("bot_id") or pdata.get("robot_id")):
                target_bot_id = pdata.get("bot_id") or pdata.get("robot_id")
        except Exception:
            pass

        print(f"[Hardware Bridge <- MQTT Motor Cmd] {topic} (target={target_bot_id}) -> '{payload_str}'", flush=True)
        dispatch_to_esp32(payload_str, target_bot_id=target_bot_id)

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

def send_to_esp32(title, message="", duration=0):
    global _message_override_until
    # Safety redirection: if called with a motor direction as single argument, route to motor dispatch!
    if not message and str(title).strip().lower() in ["forward", "reverse", "left", "right", "stop", "backward", "back", "turn_left", "turn_right"]:
        return dispatch_motor_command(str(title).strip().lower())

    if title == "Bupi Status:" and time.time() < _message_override_until:
        return
    if duration > 0:
        _message_override_until = time.time() + duration

    payload_text = f"{title} {message}".strip()
    if title == "Bupi Status:":
        payload_text = message
        
    dispatch_to_esp32(json.dumps({"title": str(title)[:16], "message": str(message)[:16]}))

def hotspot_watchdog_thread():
    """Background watchdog: continuously verifies Windows Mobile Hotspot is active for robots."""
    script_path = os.path.join(PROJECT_ROOT, "scripts", "ensure_hotspot.ps1")
    if not os.path.exists(script_path):
        return

    # Initial check on startup
    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path],
                       capture_output=True, timeout=10, startupinfo=startupinfo)
    except Exception:
        pass

    # Recurring check every 12 seconds
    while True:
        time.sleep(12)
        try:
            startupinfo = None
            if sys.platform == "win32":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run(["powershell", "-ExecutionPolicy", "Bypass", "-File", script_path],
                           capture_output=True, timeout=10, startupinfo=startupinfo)
        except Exception:
            pass

async def _ui_heartbeat_worker():
    """Periodically streams telemetry and arena snapshot to connected UI clients (1Hz) when idle."""
    while True:
        await asyncio.sleep(1.0)
        try:
            if ui_clients and _loop is not None and _loop.is_running():
                payload = build_ui_telemetry_payload("bupi_01")
                for ws in list(ui_clients):
                    try:
                        await ws.send(payload)
                    except Exception:
                        pass
        except Exception:
            pass

async def _start_server():
    global _loop
    _loop = asyncio.get_running_loop()
    print("[Hardware Bridge] Starting WebSocket Server on 0.0.0.0:8767...", flush=True)
    server = await websockets.serve(
        handle_connection, 
        "0.0.0.0", 
        8767,
        ping_interval=15,
        ping_timeout=10,
        compression=None
    )
    asyncio.create_task(_ui_heartbeat_worker())
    await asyncio.Future()  # Run forever

_server_started = False
_server_lock = threading.Lock()

def is_node_server_running() -> bool:
    return _server_started

def start_node_server():
    """Starts the WebSocket server, USB Serial supervisor, and MQTT bridge in background threads (idempotent singleton)."""
    global _server_started
    with _server_lock:
        if _server_started:
            return
        _server_started = True

    # 0. Check if port 8767 is already actively serving
    is_port_active = False
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.4)
            s.connect(("127.0.0.1", 8767))
            is_port_active = True
    except Exception:
        is_port_active = False

    if is_port_active:
        print("[Hardware Bridge] Port 8767 is already actively serving. Reusing existing WebSocket server instance.", flush=True)
    else:
        # Start WebSocket Server only if port 8767 is not already active
        def run_ws_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_start_server())
            except OSError as oe:
                print(f"[Hardware Bridge] Port 8767 already bound ({oe}). Reusing existing server.", flush=True)
            except Exception as e:
                print(f"[Hardware Bridge Error] WebSocket server fatal error: {e}", flush=True)

        ws_t = threading.Thread(target=run_ws_loop, daemon=True, name="WebSocketServer")
        ws_t.start()

    # 1. Start MQTT
    init_mqtt()

    # 2. Start USB Serial Supervisor
    serial_t = threading.Thread(target=serial_supervisor_thread, daemon=True, name="SerialSupervisor")
    serial_t.start()

    # 4. Start Telemetry DB Batch Writer Thread
    db_t = threading.Thread(target=_db_writer_worker, daemon=True, name="DbWriter")
    db_t.start()

    # 5. Start Windows Hotspot Watchdog Thread
    hs_t = threading.Thread(target=hotspot_watchdog_thread, daemon=True, name="HotspotWatchdog")
    hs_t.start()

    print("[Hardware Bridge] Unified Bridge running (Serial + WebSockets + MQTT + Hotspot Watchdog)!", flush=True)

if __name__ == "__main__":
    start_node_server()
    print("Bridge active. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping bridge...")
        serial_running = False
