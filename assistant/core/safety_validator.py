import sqlite3
import os
from core.sensor_translator import translate_sensor_value

def get_current_world_state() -> dict:
    """
    Aggregates the latest translated status of all sensors in SQLite into a single state dict.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "bupi_telemetry.db")
    
    # Default states if no readings are recorded
    state = {
        "gas": "SAFE",
        "temperature": "COMFORTABLE",
        "humidity": "NORMAL",
        "distance": "CLEAR",
        "ir": "CLEAR"
    }
    
    sensor_mappings = {
        "gas": ["mq2"],
        "temperature": ["temp", "temperature", "dht", "dht11", "dht22"],
        "humidity": ["humidity"],
        "distance": ["distance", "ultrasonic", "hcsr04"],
        "ir": ["ir"]
    }
    
    try:
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            for state_key, sensor_ids in sensor_mappings.items():
                placeholders = ",".join(["?"] * len(sensor_ids))
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
    Returns {"approved": True} or {"approved": False, "reason": "..."}.
    """
    world_state = get_current_world_state()
    topic_lower = topic.lower()
    payload_lower = str(payload).lower()
    
    # 1. Collision avoidance:
    # If distance is COLLISION_RISK or VERY_CLOSE, prevent any movement commands
    if world_state["distance"] in ["COLLISION_RISK", "VERY_CLOSE"]:
        movement_keywords = ["forward", "move", "drive", "run_motor", "motor_on", "turn_on_motor", "go_ahead"]
        is_movement = any(kw in topic_lower or kw in payload_lower for kw in movement_keywords)
        is_relay_turn_on = "relay_1" in topic_lower and ("turn_on" in payload_lower or "on" in payload_lower or "1" in payload_lower)
        
        if is_movement or is_relay_turn_on:
            return {
                "approved": False,
                "reason": f"Collision Avoidance: Action blocked because distance state is {world_state['distance']}."
            }
            
    # 2. Gas safety:
    # If gas is DANGER or CRITICAL, prevent turning off ventilation relays or critical actuators
    if world_state["gas"] in ["DANGER", "CRITICAL"]:
        is_relay_turn_off = "relay_1" in topic_lower and ("turn_off" in payload_lower or "off" in payload_lower or "0" in payload_lower)
        if is_relay_turn_off:
            return {
                "approved": False,
                "reason": f"Gas Safety: Blocked attempt to turn off ventilation while gas status is {world_state['gas']}."
            }
            
    return {"approved": True}
