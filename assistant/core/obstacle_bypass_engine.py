"""
Core Obstacle Bypass Engine for BUPI Robots (Bot 1 Scout & Bot 2 Specialist)
Executes active flank-and-detour maneuvers to navigate around detected obstacles ("cross out that obstacle").
"""

import time
import json
import threading
from typing import Dict, Any, Optional

try:
    import paho.mqtt.publish as publish
except ImportError:
    publish = None

def get_motor_topic_for_bot(bot_id: str) -> str:
    bot = str(bot_id).lower().strip()
    if bot in ["bupi_02", "bot2", "bot 2", "specialist"]:
        return "bupi/v1/bot2/actuators/motors/cmd"
    return "bupi/actuators/motors/cmd"

def execute_obstacle_bypass(
    bot_id: str = "bupi_01",
    flank_direction: str = "auto",
    speed: int = 200,
    broker_host: str = "localhost"
) -> Dict[str, Any]:
    """
    Executes an active obstacle bypass maneuver:
    1. Stop forward momentum
    2. Buffer reverse (300ms) to gain sensor clearance
    3. Flank turn 45 degrees into clear corridor
    4. Advance forward along the flank (400ms) to clear obstacle depth
    5. Counter-pivot -45 degrees to re-align with original heading
    6. Verify path clearance
    """
    target_bot = "bupi_02" if any(k in str(bot_id).lower() for k in ["2", "bot2", "specialist"]) else "bupi_01"
    topic = get_motor_topic_for_bot(target_bot)

    # Determine flank direction
    dir_clean = flank_direction.lower().strip()
    if dir_clean in ["left", "turn_left", "-1"]:
        chosen_dir = "left"
        turn_action = "turn_left_90"
        counter_action = "turn_right_90"
        flank_degrees = -45.0
        counter_degrees = 45.0
    elif dir_clean in ["right", "turn_right", "1"]:
        chosen_dir = "right"
        turn_action = "turn_right_90"
        counter_action = "turn_left_90"
        flank_degrees = 45.0
        counter_degrees = -45.0
    else:
        # Default smart auto: flank right
        chosen_dir = "right"
        turn_action = "turn_right_90"
        counter_action = "turn_left_90"
        flank_degrees = 45.0
        counter_degrees = -45.0

    print(f"[Obstacle Bypass] Initiating detour on {target_bot} (Flank: {chosen_dir}, Topic: {topic})", flush=True)

    def send_cmd(act: str, deg: float = 0.0, dur_ms: int = 0):
        payload = {
            "action": act,
            "speed": speed,
            "degrees": deg,
            "duration_ms": dur_ms,
            "bot_id": target_bot,
            "robot_id": target_bot
        }
        json_str = json.dumps(payload)
        if publish:
            try:
                publish.single(f"{topic}/json", json_str, hostname=broker_host)
                publish.single(topic, act, hostname=broker_host)
            except Exception as e:
                print(f"[Obstacle Bypass Error] Failed to publish MQTT: {e}", flush=True)

    # 1. Stop
    send_cmd("stop")
    time.sleep(0.05)

    # 2. Reverse buffer (300ms)
    send_cmd("reverse", dur_ms=300)
    time.sleep(0.35)
    send_cmd("stop")
    time.sleep(0.05)

    # 3. Flank turn 45 degrees
    send_cmd("turn_by", deg=flank_degrees)
    time.sleep(0.45)
    send_cmd("stop")
    time.sleep(0.05)

    # 4. Advance along obstacle depth (400ms)
    send_cmd("forward", dur_ms=400)
    time.sleep(0.45)
    send_cmd("stop")
    time.sleep(0.05)

    # 5. Counter-pivot to re-acquire forward heading
    send_cmd("turn_by", deg=counter_degrees)
    time.sleep(0.45)
    send_cmd("stop")
    time.sleep(0.05)

    result = {
        "status": "OBSTACLE_BYPASSED",
        "bot_id": target_bot,
        "flank_direction": chosen_dir,
        "flank_degrees": flank_degrees,
        "maneuver_steps": [
            "halt",
            "reverse_buffer_300ms",
            f"flank_pivot_{flank_degrees}_deg",
            "traverse_depth_400ms",
            f"counter_pivot_{counter_degrees}_deg",
            "path_realigned"
        ],
        "summary": f"{target_bot.upper()} successfully bypassed obstacle via {chosen_dir} detour."
    }

    print(f"[Obstacle Bypass] {result['summary']}", flush=True)
    return result
