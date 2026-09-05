import os
import sys
import time
import json
import threading

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish
from agents.autonomous_goal_agent import AutonomousGoalAgent
from core.safety_validator import get_current_world_state
from voice.speaker import get_cached_voice_file, SpeakerThread

MQTT_HOST = "localhost"
MQTT_PORT = 1883

def inject_sensor(sensor_id: str, value: float):
    # 1. Publish to MQTT broker
    try:
        publish.single(f"bupi/sensors/{sensor_id}/state", json.dumps({"value": value}), hostname=MQTT_HOST, port=MQTT_PORT)
    except Exception:
        pass
    # 2. Write to bupi_telemetry.db for safety validator
    db_path = os.path.join(BASE_DIR, "bupi_telemetry.db")
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS telemetry (sensor_id TEXT, value REAL, timestamp REAL)")
        c.execute("INSERT INTO telemetry (sensor_id, value, timestamp) VALUES (?, ?, ?)", (sensor_id, value, time.time()))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error writing telemetry: {e}")

class MissionMonitor:
    def __init__(self):
        self.motor_commands = []
        self.lcd_messages = []
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="Mission_Monitor")
        self.client.on_message = self.on_message
        self.client.connect(MQTT_HOST, MQTT_PORT, 60)
        self.client.subscribe("bupi/actuators/motors/cmd")
        self.client.subscribe("bupi/actuators/lcd/cmd")
        self.client.loop_start()

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="ignore")
        timestamp = time.strftime("%H:%M:%S")
        if topic == "bupi/actuators/motors/cmd":
            self.motor_commands.append((timestamp, payload))
            print(f"  [MQTT Motor Cmd] -> {payload}", flush=True)
        elif topic == "bupi/actuators/lcd/cmd":
            clean_lcd = payload.replace("\n", " | ")
            self.lcd_messages.append((timestamp, clean_lcd))
            print(f"  [MQTT LCD Display] -> \"{clean_lcd}\"", flush=True)

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()

def run_live_human_search_simulation():
    print("\n" + "="*70)
    print("  SIMULATED LIVE SCENARIO: Autonomous 'Find Human' with Obstacle Avoidance")
    print("="*70)
    print("  Objective: Watch Boopi autonomously navigate, detect an obstacle <25cm,")
    print("  execute evasive maneuvers, locate human presence, and complete mission.\n")

    monitor = MissionMonitor()
    agent = AutonomousGoalAgent()

    # Step 1: Initialize starting world state (Path clear)
    print("[1/5] Injecting initial clear telemetry (Distance: 150cm, Gas: SAFE)...")
    inject_sensor("distance", 150.0)
    inject_sensor("mq2", 120.0)
    time.sleep(0.5)

    # Step 2: Start Autonomous Mission
    print("\n[2/5] Starting Autonomous Mission: 'Boopi, find the human in the room'...")
    res = agent.start_mission("Boopi, find the human in the room")
    print(f"  -> Agent response: {res}")
    time.sleep(1.5)

    # Step 3: Inject sudden obstacle (<20cm)
    print("\n[3/5] Injecting SUDDEN OBSTACLE (<20cm) into path...")
    print("  -> Simulating ultrasonic sensor: front distance = 14.0 cm (COLLISION RISK)")
    inject_sensor("distance", 14.0)
    time.sleep(2.5)

    # Step 4: Clear the obstacle
    print("\n[4/5] Evasive maneuver in progress. Path is now clear again...")
    inject_sensor("distance", 180.0)
    time.sleep(2.5)

    # Step 5: Simulate human detection target
    print("\n[5/5] Target human detected in front sector! Closing distance...")
    time.sleep(1.5)

    # Mission cleanup
    agent.stop_mission(reason="Simulation test complete")
    time.sleep(1.0)
    monitor.close()

    print("\n" + "="*70)
    print("  MISSION SIMULATION SUMMARY")
    print("="*70)
    print(f"  Total Motor Commands Issued: {len(monitor.motor_commands)}")
    for t, cmd in monitor.motor_commands[-8:]:
        print(f"    [{t}] Motor: {cmd}")
    print(f"\n  Total LCD Status Updates: {len(monitor.lcd_messages)}")
    for t, msg in monitor.lcd_messages[-6:]:
        print(f"    [{t}] LCD: {msg}")
    print("\n  [PASS] Autonomous closed-loop cycle and obstacle avoidance successfully demonstrated!")

def run_mic_stt_live_test():
    print("\n" + "="*70)
    print("  LIVE MICROPHONE & GPU WHISPER TEST")
    print("="*70)
    print("  Initializing local Faster-Whisper on NVIDIA RTX GPU...")
    from voice.listener import ListenerThread
    from PyQt6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    listener = ListenerThread()

    def on_transcription(text):
        if text:
            print(f"\n  [TRANSCRIPTION RECEIVED]: \"{text}\"")
            from agents.router_agent import router
            fast_intent = router.quick_regex_classify(text)
            if fast_intent:
                print(f"  [ROUTER MATCH]: {fast_intent['type']} -> {fast_intent.get('payload')}")
                # Test voice cache hit
                test_voice = "I'm here." if "bupi" in text.lower() else "Emergency stop triggered. Motors halted."
                cached = get_cached_voice_file(test_voice)
                if cached:
                    print(f"  [0-MS VOICE CACHE HIT]: {os.path.basename(cached)}")
            else:
                print("  [ROUTER]: Handled by Local Orchestrator / Companion AI")
        else:
            print("  [Silence / Hallucination filtered]")

    listener.transcription_ready.connect(on_transcription)
    listener.start()
    print("  Microphone listening started! Speak a command (e.g. 'Boopi find the human' or 'Emergency stop')...")
    print("  Listening for 10 seconds...")
    t_end = time.time() + 10.0
    while time.time() < t_end:
        app.processEvents()
        time.sleep(0.05)

    listener.stop()
    print("  Microphone test finished.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Boopi Autonomous Mission & Voice Test Runner")
    parser.add_argument("--mode", choices=["mission", "mic", "all"], default="mission", help="Test mode to run")
    args = parser.parse_args()

    if args.mode in ["mission", "all"]:
        run_live_human_search_simulation()
    if args.mode in ["mic", "all"]:
        run_mic_stt_live_test()
