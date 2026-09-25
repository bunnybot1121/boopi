import sqlite3
import os
import time
from core.sensor_translator import translate_sensor_value

TELEMETRY_TTL_SECONDS = 15.0  # Telemetry older than 15 seconds is marked UNKNOWN_STALE

def get_current_world_state(bot_id: str = "bupi_01") -> dict:
    """
    Aggregates the latest translated status of all sensors in SQLite and in-memory cache into a single state dict.
    Enforces a strict Telemetry TTL check to prevent acting on stale/frozen sensor readings.
    Supports targeting a specific robot ('bupi_01' Scout vs 'bupi_02' Specialist).
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "bupi_telemetry.db")
    now = time.time()
    
    # Default states if no readings are recorded
    state = {
        "bot_id": bot_id,
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
        "gas": [f"{bot_id}_mq2", "mq2"],
        "temperature": [f"{bot_id}_temp", f"{bot_id}_temperature", "temp", "temperature", "dht", "dht11", "dht22"],
        "humidity": [f"{bot_id}_humidity", "humidity"],
        "distance": [f"{bot_id}_distance", "distance", "ultrasonic", "hcsr04"],
        "ir": [f"{bot_id}_ir", "ir"],
        "pir": [f"{bot_id}_pir", "pir"],
        "tilt": [f"{bot_id}_tilt", "pitch", "roll", "tilt", "mpu6050"],
        "heading": [f"{bot_id}_heading", "heading", "yaw"]
    }
    
    # 1. First check in-memory live telemetry from bupi_node_server if available
    try:
        from bupi_node_server import get_latest_telemetry
        live_t = get_latest_telemetry(bot_id)
        live_b2 = get_latest_telemetry("bupi_02") if bot_id != "bupi_02" else live_t
        has_fresh_t = live_t.get("updated_at", 0) > 0 and (now - live_t["updated_at"]) < TELEMETRY_TTL_SECONDS
        has_fresh_b2 = live_b2.get("updated_at", 0) > 0 and (now - live_b2["updated_at"]) < TELEMETRY_TTL_SECONDS

        if has_fresh_t or has_fresh_b2:
            source = live_t if has_fresh_t else live_b2
            dist_val = source.get("distance_cm", 150.0)
            state["distance"] = translate_sensor_value("distance", dist_val)["status"]
            tilt_val = source.get("effective_tilt", 0.0)
            state["tilt"] = translate_sensor_value("tilt", tilt_val)["status"]
            state["pir"] = translate_sensor_value("pir", live_t.get("pir", 0))["status"]

            # Pull live environmental metrics from Bot 2 (Specialist)
            gas_val = live_b2.get("gas_ppm", live_b2.get("mq2_raw", 0.0)) if has_fresh_b2 else source.get("gas_ppm", 0.0)
            state["gas"] = translate_sensor_value("mq2", gas_val)["status"]
            temp_val = live_b2.get("temp_c", live_b2.get("temperature_c", 25.0)) if has_fresh_b2 else source.get("temp_c", 25.0)
            state["temperature"] = translate_sensor_value("temperature", temp_val)["status"]
            hum_val = live_b2.get("humidity", 50.0) if has_fresh_b2 else source.get("humidity", 50.0)
            state["humidity"] = translate_sensor_value("humidity", hum_val)["status"]
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

ENABLE_OBSTACLE_AVOIDANCE = False  # Set to False to disable obstacle blocking
ENABLE_TILT_SAFETY = False         # Set to False to disable tilt blocking

def validate_safety(topic: str, payload: str, bot_id: str = None) -> dict:
    """
    Validates a planned hardware action/command against the current world state.
    Supports dual-robot routing ('bupi_01' vs 'bupi_02').
    Returns {"approved": True} or {"approved": False, "reason": "..."}.
    """
    topic_lower = topic.lower()
    payload_lower = str(payload).lower()
    
    target_bot = bot_id
    if not target_bot:
        if "bot2" in topic_lower or "bupi_02" in topic_lower or "bot2" in payload_lower or "bupi_02" in payload_lower:
            target_bot = "bupi_02"
        else:
            target_bot = "bupi_01"

    world_state = get_current_world_state(bot_id=target_bot)
    
    # 1. Collision Avoidance (Bypassed when ENABLE_OBSTACLE_AVOIDANCE is False):
    if ENABLE_OBSTACLE_AVOIDANCE and world_state["distance"] in ["COLLISION_RISK", "VERY_CLOSE"]:
        forward_movement_keywords = ["forward", "move_forward", "drive_forward", "go_ahead", "run_motor"]
        reverse_evasive_keywords = ["reverse", "backward", "back", "turn_left", "turn_right", "left", "right", "stop"]
        
        is_forward_movement = any(kw in topic_lower or kw in payload_lower for kw in forward_movement_keywords)
        is_evasive_action = any(kw in topic_lower or kw in payload_lower for kw in reverse_evasive_keywords)
        if is_forward_movement and not is_evasive_action:
            return {
                "approved": False,
                "reason": f"[{target_bot}] Directional Safety Cutoff: Forward action blocked because distance state is {world_state['distance']}."
            }

    # 2. Tilt Hazard Cutoff (Bypassed when ENABLE_TILT_SAFETY is False):
    if ENABLE_TILT_SAFETY and world_state.get("tilt") == "TILT_HAZARD":
        motor_movement_keywords = ["forward", "reverse", "left", "right", "move", "turn"]
        if any(kw in topic_lower or kw in payload_lower for kw in motor_movement_keywords) and "stop" not in payload_lower:
            return {
                "approved": False,
                "reason": f"[{target_bot}] Tilt Hazard Cutoff: Motor movement blocked because chassis tilt exceeds safety boundary."
            }
            
    # 3. Gas & Environmental Hazard Cutoff:
    if world_state.get("gas") in ["DANGER", "CRITICAL"]:
        forward_movement_keywords = ["forward", "move_forward", "drive_forward", "go_ahead"]
        reverse_evasive_keywords = ["reverse", "backward", "back", "turn_left", "turn_right", "left", "right", "stop"]
        is_forward = any(kw in topic_lower or kw in payload_lower for kw in forward_movement_keywords)
        is_evasive = any(kw in topic_lower or kw in payload_lower for kw in reverse_evasive_keywords)
        
        # Prevent driving forward deeper into flammable/toxic gas plume, allow reverse/turn evasion
        if is_forward and not is_evasive:
            return {
                "approved": False,
                "reason": f"[{target_bot}] Gas Hazard Cutoff: Forward driving blocked into critical gas concentration ({world_state['gas']}). Reverse or turn away."
            }
            
        is_relay_turn_off = "relay_1" in topic_lower and ("turn_off" in payload_lower or "off" in payload_lower or "0" in payload_lower)
        if is_relay_turn_off:
            return {
                "approved": False,
                "reason": f"Gas Safety: Blocked attempt to turn off ventilation while gas status is {world_state['gas']}."
            }
            
    return {"approved": True}


