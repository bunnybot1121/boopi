import sqlite3
import os
import time
from core.sensor_translator import translate_sensor_value

TELEMETRY_TTL_SECONDS = 15.0  # Telemetry older than 15 seconds is marked UNKNOWN_STALE

def get_current_world_state() -> dict:
    """
    Aggregates the latest translated status of all sensors in SQLite and in-memory cache into a single state dict.
    Enforces a strict Telemetry TTL check to prevent acting on stale/frozen sensor readings.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "bupi_telemetry.db")
    now = time.time()
    
    # Default states if no readings are recorded
    state = {
        "gas": "SAFE",
        "temperature": "COMFORTABLE",
        "humidity": "NORMAL",
        "distance": "CLEAR",
        "ir": "CLEAR",
        "pir": "QUIET",
        "tilt": "LEVEL",
        "heading": "HEADING_TRACKING",
        "telemetry_fresh": True
    }
    
    sensor_mappings = {
        "gas": ["mq2"],
        "temperature": ["temp", "temperature", "dht", "dht11", "dht22"],
        "humidity": ["humidity"],
        "distance": ["distance", "ultrasonic", "hcsr04"],
        "ir": ["ir"],
        "pir": ["pir"],
        "tilt": ["pitch", "roll", "tilt", "mpu6050"],
        "heading": ["heading", "yaw"]
    }
    
    # 1. First check in-memory live telemetry from bupi_node_server if available
    try:
        from bupi_node_server import get_latest_telemetry
        live_t = get_latest_telemetry()
        if live_t.get("updated_at", 0) > 0 and (now - live_t["updated_at"]) < TELEMETRY_TTL_SECONDS:
            dist_val = live_t.get("distance_cm", 150.0)
            state["distance"] = translate_sensor_value("distance", dist_val)["status"]
            tilt_val = live_t.get("effective_tilt", 0.0)
            state["tilt"] = translate_sensor_value("tilt", tilt_val)["status"]
            state["pir"] = translate_sensor_value("pir", live_t.get("pir", 0))["status"]
            state["heading"] = "HEADING_TRACKING"
            state["telemetry_fresh"] = True
            return state
    except Exception:
        pass

    try:
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path, timeout=1.0)
            cursor = conn.cursor()
            
            for state_key, sensor_ids in sensor_mappings.items():
                placeholders = ",".join(["?"] * len(sensor_ids))
                # Check if timestamp column exists in telemetry table
                cursor.execute("PRAGMA table_info(telemetry)")
                cols = [col[1] for col in cursor.fetchall()]
                
                if "timestamp" in cols:
                    query = f"SELECT value, sensor_id, timestamp FROM telemetry WHERE sensor_id IN ({placeholders}) ORDER BY rowid DESC LIMIT 1"
                    cursor.execute(query, sensor_ids)
                    row = cursor.fetchone()
                    if row is not None:
                        val, s_id, ts = row
                        if ts is not None and (now - float(ts)) > TELEMETRY_TTL_SECONDS:
                            state[state_key] = "UNKNOWN_STALE"
                            state["telemetry_fresh"] = False
                        else:
                            translation = translate_sensor_value(s_id, val)
                            state[state_key] = translation["status"]
                else:
                    query = f"SELECT value, sensor_id FROM telemetry WHERE sensor_id IN ({placeholders}) ORDER BY rowid DESC LIMIT 1"
                    cursor.execute(query, sensor_ids)
                    row = cursor.fetchone()
                    if row is not None:
                        val, s_id = row
                        translation = translate_sensor_value(s_id, val)
                        state[state_key] = translation["status"]
            conn.close()
    except Exception as e:
        print(f"[Safety Validator] Error querying SQLite world state: {e}", flush=True)
        
    return state

def validate_safety(topic: str, payload: str) -> dict:
    """
    Validates a planned hardware action/command against the current world state.
    Enforces directional movement safety (allows reverse/evasive maneuvers while blocking forward motion into hazards).
    Returns {"approved": True} or {"approved": False, "reason": "..."}.
    """
    world_state = get_current_world_state()
    topic_lower = topic.lower()
    payload_lower = str(payload).lower()
    
    # 1. Collision Avoidance (Blocks forward motion toward obstacle while allowing reverse/evasion):
    if world_state["distance"] in ["COLLISION_RISK", "VERY_CLOSE"]:
        forward_movement_keywords = ["forward", "move_forward", "drive_forward", "go_ahead", "run_motor"]
        reverse_evasive_keywords = ["reverse", "backward", "back", "turn_left", "turn_right", "left", "right", "stop"]
        
        is_forward_movement = any(kw in topic_lower or kw in payload_lower for kw in forward_movement_keywords)
        is_evasive_action = any(kw in topic_lower or kw in payload_lower for kw in reverse_evasive_keywords)
        # Block forward movements toward obstacle, but permit reverse/turn evasive maneuvers
        if is_forward_movement and not is_evasive_action:
            return {
                "approved": False,
                "reason": f"Directional Safety Cutoff: Forward action blocked because distance state is {world_state['distance']}."
            }

    # 2. Tilt Hazard Cutoff:
    if world_state.get("tilt") == "TILT_HAZARD":
        motor_movement_keywords = ["forward", "reverse", "left", "right", "move", "turn"]
        if any(kw in topic_lower or kw in payload_lower for kw in motor_movement_keywords) and "stop" not in payload_lower:
            return {
                "approved": False,
                "reason": "Tilt Hazard Cutoff: Motor movement blocked because chassis tilt exceeds 35° safety boundary."
            }
            
    # 3. Gas safety:
    if world_state["gas"] in ["DANGER", "CRITICAL"]:
        is_relay_turn_off = "relay_1" in topic_lower and ("turn_off" in payload_lower or "off" in payload_lower or "0" in payload_lower)
        if is_relay_turn_off:
            return {
                "approved": False,
                "reason": f"Gas Safety: Blocked attempt to turn off ventilation while gas status is {world_state['gas']}."
            }
            
    return {"approved": True}


