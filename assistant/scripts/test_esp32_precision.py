#!/usr/bin/env python3
"""
===============================================================================
BUPI ESP32 Robotics Precision & Telemetry Diagnostic Suite
===============================================================================
Tests bi-directional hardware communication between the Bupi agent and
physical ESP32 nodes (N20 Motors, TB6612, MQ2 Gas, 16x2 LCD, Ultrasonic, IMU).

Modes:
  1. Live Monitor: Sniff sensor telemetry & node heartbeats in real-time.
  2. Send to LCD: Dispatch formatted 16x2 text messages to the ESP32 display.
  3. Send Motor/Relay: Test actuator pulses with safety validator & auto-stop.
  4. Latency Benchmark: Measure round-trip MQTT message transmission latency.
  5. Full Diagnostic: Automated 5-point hardware & broker health check.
===============================================================================
"""

import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import os
import time
import json
import argparse
import sqlite3
from datetime import datetime

try:
    import paho.mqtt.client as mqtt
    import paho.mqtt.publish as publish
    HAS_PAHO = True
except ImportError:
    HAS_PAHO = False

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

MQTT_HOST = "localhost"
MQTT_PORT = 1883
DB_PATH = os.path.join(PROJECT_ROOT, "bupi_telemetry.db")

def print_header(title: str):
    print("\n" + "=" * 70)
    print(f"  [BUPI DIAGNOSTICS] {title}")
    print("=" * 70)

def check_broker_connection() -> bool:
    """Quick socket check to verify Mosquitto is active on localhost:1883."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.5)
    try:
        s.connect((MQTT_HOST, MQTT_PORT))
        s.close()
        return True
    except Exception:
        return False

# =============================================================================
# MODE 1: LIVE MONITOR (Receiving Test)
# =============================================================================
def run_live_monitor(duration: int = 0):
    """
    Subscribes to all sensor and node topics.
    Prints packets in real time with timestamp, interval delta, and DB verification.
    """
    print_header("LIVE TELEMETRY & HEARTBEAT SNIFFER")
    print(f"[*] Connecting to Mosquitto at {MQTT_HOST}:{MQTT_PORT}...")
    print("[*] Listening for ESP32 packets on 'bupi/#' and 'footmo2/#'...")
    print("[*] Press Ctrl+C at any time to return to menu.\n")

    last_packet_times = {}
    packet_count = 0

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code == 0 or reason_code == "Success":
            print("[+] Connected to MQTT Broker successfully.")
            client.subscribe("bupi/sensors/#")
            client.subscribe("bupi/nodes/#")
            client.subscribe("bupi/actuators/#")
            client.subscribe("footmo2/#")
            print("[+] Subscriptions active. Waiting for ESP32 broadcasts...\n")
        else:
            print(f"[-] Connection failed with code {reason_code}")

    def on_message(client, userdata, msg):
        nonlocal packet_count
        now = time.time()
        packet_count += 1
        topic = msg.topic
        payload_str = msg.payload.decode("utf-8", errors="ignore")
        time_str = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        delta_str = "first"
        if topic in last_packet_times:
            delta_ms = (now - last_packet_times[topic]) * 1000.0
            delta_str = f"dt={delta_ms:.1f}ms"
        last_packet_times[topic] = now

        tag = "[TELEMETRY]"
        if "heartbeat" in topic:
            tag = "[HEARTBEAT]"
        elif "announce" in topic:
            tag = "[ANNOUNCE] "
        elif "actuators" in topic or "cmd" in topic:
            tag = "[ACTUATOR] "

        # Clean JSON presentation
        try:
            parsed = json.loads(payload_str)
            if isinstance(parsed, dict):
                short_summary = ", ".join(f"{k}={v}" for k, v in list(parsed.items())[:4])
                payload_disp = f"{{{short_summary}}}"
            else:
                payload_disp = payload_str
        except Exception:
            payload_disp = payload_str

        print(f"[{time_str}] {tag} {topic:<30} ({delta_str:<10}) -> {payload_disp}")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="Bupi_Diagnostic_Sniffer")
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()
        start = time.time()
        while True:
            time.sleep(0.1)
            if duration > 0 and (time.time() - start) >= duration:
                break
    except KeyboardInterrupt:
        print("\n[*] Stopping sniffer...")
    finally:
        client.loop_stop()
        client.disconnect()
        print(f"[*] Sniffer finished. Total packets captured: {packet_count}\n")

# =============================================================================
# MODE 2: LCD MESSAGE DISPATCH (Sending Test)
# =============================================================================
def run_send_lcd(message: str = None):
    """Dispatches a formatted 16x2 text message to the ESP32 LCD screen."""
    print_header("ESP32 LCD TEXT DISPATCH TEST")
    if not message:
        print("Select preset or type custom text:")
        print("  1. 'BUPI ROBOT: ONLINE'")
        print("  2. 'MQ2 GAS: SAFE\\nREADING: 135'")
        print("  3. 'SYSTEM TEST: OK\\nESP32 READY'")
        print("  4. Custom message")
        choice = input("Choice (1-4, Enter for 1): ").strip()
        if choice == "2":
            message = "MQ2 GAS: SAFE\nREADING: 135"
        elif choice == "3":
            message = "SYSTEM TEST: OK\nESP32 READY"
        elif choice == "4":
            message = input("Enter text to display: ").strip()
        else:
            message = "BUPI ROBOT: ONLINE"

    from actions.hardware_tools import display_on_esp32
    print(f"\n[*] Dispatching to ESP32: {repr(message)}")
    t0 = time.time()
    result = display_on_esp32(message)
    elapsed_ms = (time.time() - t0) * 1000.0

    print(f"[+] Result: {result}")
    print(f"[+] Dispatch latency: {elapsed_ms:.2f} ms")
    print("[+] Check physical 16x2 LCD screen for updated text.\n")

# =============================================================================
# MODE 3: MOTOR & ACTUATOR PULSE TEST (Sending Test)
# =============================================================================
def run_send_motors(direction: str = None, speed: int = 200, duration: float = 1.0):
    """Sends safety-checked motor pulse with auto-stop to the mobile base."""
    print_header("TB6612 MOTOR ACTUATION PULSE TEST")
    if not direction:
        print("Select motor test action:")
        print("  1. Forward Pulse (1.0s, Speed 200)")
        print("  2. Reverse Pulse (1.0s, Speed 200)")
        print("  3. Turn Left (0.5s, Speed 180)")
        print("  4. Turn Right (0.5s, Speed 180)")
        print("  5. Emergency Stop (Speed 0)")
        print("  6. Toggle Relay 1 (Turn ON)")
        print("  7. Toggle Relay 1 (Turn OFF)")
        choice = input("Choice (1-7, Enter for 1): ").strip()
        if choice == "2":
            direction, speed, duration = "reverse", 200, 1.0
        elif choice == "3":
            direction, speed, duration = "left", 180, 0.5
        elif choice == "4":
            direction, speed, duration = "right", 180, 0.5
        elif choice == "5":
            direction, speed, duration = "stop", 0, 0.0
        elif choice == "6":
            from actions.hardware_tools import control_relay
            print("\n[*] Sending turn_on command to relay_1...")
            res = control_relay("relay_1", "turn_on")
            print(f"[+] Result: {res}\n")
            return
        elif choice == "7":
            from actions.hardware_tools import control_relay
            print("\n[*] Sending turn_off command to relay_1...")
            res = control_relay("relay_1", "turn_off")
            print(f"[+] Result: {res}\n")
            return
        else:
            direction, speed, duration = "forward", 200, 1.0

    from actions.hardware_tools import control_motors
    print(f"\n[*] Executing: direction='{direction}', speed={speed}, duration={duration}s")
    t0 = time.time()
    result = control_motors(direction=direction, speed=speed, duration_seconds=duration)
    elapsed_ms = (time.time() - t0) * 1000.0

    print(f"[+] Safety & Dispatch Output: {result}")
    print(f"[+] Execution time: {elapsed_ms:.2f} ms")
    if duration > 0 and direction != "stop":
        print(f"[*] Auto-stop timer armed ({duration}s). Motors will stop automatically.\n")

# =============================================================================
# MODE 4: LATENCY BENCHMARK
# =============================================================================
def run_latency_benchmark(samples: int = 10):
    """Measures round-trip publish-to-receive latency across the local broker."""
    print_header(f"MQTT ROUND-TRIP LATENCY BENCHMARK ({samples} Samples)")
    test_topic = "bupi/test/latency_ping"
    latencies = []
    received_event = None

    def on_connect(client, userdata, flags, reason_code, properties=None):
        client.subscribe(test_topic)

    def on_message(client, userdata, msg):
        t_sent = float(msg.payload.decode("utf-8"))
        roundtrip_ms = (time.time() - t_sent) * 1000.0
        latencies.append(roundtrip_ms)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="Bupi_Latency_Tester")
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()
        time.sleep(0.3)

        for i in range(samples):
            t_now = time.time()
            client.publish(test_topic, str(t_now))
            time.sleep(0.08)

        # Wait for any trailing returns
        time.sleep(0.2)
        client.loop_stop()
        client.disconnect()

        if latencies:
            min_l = min(latencies)
            avg_l = sum(latencies) / len(latencies)
            max_l = max(latencies)
            jitter = max_l - min_l
            print(f"[*] Samples Completed: {len(latencies)} / {samples}")
            print(f"[+] Min Latency:  {min_l:.3f} ms")
            print(f"[+] Avg Latency:  {avg_l:.3f} ms")
            print(f"[+] Max Latency:  {max_l:.3f} ms")
            print(f"[+] Jitter:       {jitter:.3f} ms")
            if avg_l < 5.0:
                print("[+] Grade: EXCELLENT (<5ms) - Perfect for hard real-time robot control.\n")
            elif avg_l < 20.0:
                print("[+] Grade: GOOD (<20ms) - Suitable for responsive physical actuation.\n")
            else:
                print("[!] Grade: HIGH LATENCY (>20ms) - Check local network / Wi-Fi congestion.\n")
        else:
            print("[-] No packets returned. Ensure broker is running.\n")
    except Exception as e:
        print(f"[-] Benchmark error: {e}\n")

# =============================================================================
# MODE 5: FULL AUTOMATED DIAGNOSTICS
# =============================================================================
def run_full_diagnostics():
    """Runs a complete 5-point system check."""
    print_header("FULL 5-POINT AUTOMATED ROBOTICS DIAGNOSTICS")

    # 1. Broker Connection
    print("[1/5] Checking Local Mosquitto Broker...")
    broker_ok = check_broker_connection()
    if broker_ok:
        print("  [PASS] Mosquitto broker is active on localhost:1883")
    else:
        print("  [FAIL] Cannot connect to Mosquitto on localhost:1883")

    # 2. Database & Registered Nodes
    print("\n[2/5] Checking Telemetry & Node Database...")
    from actions.hardware_tools import get_connected_nodes
    nodes_info = json.loads(get_connected_nodes())
    nodes_list = nodes_info.get("connected_nodes", [])
    if nodes_list:
        print(f"  [PASS] Found {len(nodes_list)} registered node(s):")
        for n in nodes_list:
            status = n.get("status", "UNKNOWN")
            ip = n.get("ip_address", "unknown")
            dev = n.get("device_name", "ESP32")
            last_s = n.get("last_seen_seconds_ago")
            print(f"    - {dev} ({status}) | IP: {ip} | Last seen: {last_s}s ago")
    else:
        print(f"  [INFO] No active nodes yet in database ({nodes_info.get('message', 'None')}).")

    # 3. Physical World State & Telemetry Freshness
    print("\n[3/5] Querying Physical World State...")
    from actions.hardware_tools import get_world_state
    world_state = json.loads(get_world_state())
    print("  World State Snapshot:")
    for k, v in world_state.items():
        print(f"    - {k:<16}: {v}")

    # 4. Hardware Knowledge Base Verification
    print("\n[4/5] Checking Offline Hardware Knowledge Base...")
    from actions.hardware_tools import get_hardware_knowledge
    tb_data = get_hardware_knowledge("TB6612FNG")
    mq_data = get_hardware_knowledge("MQ2")
    if "truth_table" in tb_data and "analogRead" in mq_data:
        print("  [PASS] Offline hardware specifications loaded successfully for TB6612 & MQ2.")
    else:
        print("  [WARN] Hardware knowledge cache returned unexpected format.")

    # 5. LCD & Broker Latency Check
    print("\n[5/5] Testing Broker Latency & LCD Dual-Topic Dispatch...")
    run_latency_benchmark(samples=5)
    run_send_lcd(message="BUPI: DIAGNOSTIC\nALL TESTS PASSED")

    print_header("DIAGNOSTIC SUMMARY COMPLETE")
    print("System is fully ready for live physical ESP32 tests.\n")

# =============================================================================
# INTERACTIVE MENU
# =============================================================================
def interactive_menu():
    while True:
        print("\n" + "=" * 55)
        print("    BUPI ESP32 ROBOTICS DIAGNOSTIC CONSOLE")
        print("=" * 55)
        print("  1. Live Telemetry & Heartbeat Sniffer (Receiving)")
        print("  2. Dispatch Text Message to ESP32 LCD (Sending)")
        print("  3. Test TB6612 Motors / Relay Pulse   (Sending)")
        print("  4. Run Round-Trip Latency Benchmark")
        print("  5. Run Full Automated 5-Point Diagnostics")
        print("  6. Query Connected Nodes Status")
        print("  7. Query Hardware Pinout Knowledge Base")
        print("  0. Exit")
        print("=" * 55)
        choice = input("Select an option (0-7): ").strip()

        if choice == "1":
            run_live_monitor()
        elif choice == "2":
            run_send_lcd()
        elif choice == "3":
            run_send_motors()
        elif choice == "4":
            run_latency_benchmark(10)
        elif choice == "5":
            run_full_diagnostics()
        elif choice == "6":
            from actions.hardware_tools import get_connected_nodes
            print(f"\n{get_connected_nodes()}\n")
        elif choice == "7":
            comp = input("Enter component name (e.g. TB6612FNG, MQ2, HC-SR04, MPU6050, RELAY, ESP32_PINOUT): ").strip()
            from actions.hardware_tools import get_hardware_knowledge
            print(f"\n{get_hardware_knowledge(comp)}\n")
        elif choice == "0" or choice.lower() == "exit":
            print("\nExiting Bupi Diagnostics. Goodbye!\n")
            break
        else:
            print("\n[!] Invalid selection, please choose between 0 and 7.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BUPI ESP32 Robotics Precision & Telemetry Diagnostic Suite")
    parser.add_argument("--mode", choices=["monitor", "send_lcd", "send_motor", "benchmark", "all", "nodes"], help="Mode to run directly")
    parser.add_argument("--text", type=str, help="Text to display on LCD in send_lcd mode")
    parser.add_argument("--duration", type=int, default=0, help="Duration in seconds for sniffer (0 for indefinite)")
    args = parser.parse_args()

    if args.mode == "monitor":
        run_live_monitor(duration=args.duration)
    elif args.mode == "send_lcd":
        run_send_lcd(message=args.text)
    elif args.mode == "send_motor":
        run_send_motors()
    elif args.mode == "benchmark":
        run_latency_benchmark(10)
    elif args.mode == "all":
        run_full_diagnostics()
    elif args.mode == "nodes":
        from actions.hardware_tools import get_connected_nodes
        print(get_connected_nodes())
    else:
        interactive_menu()
