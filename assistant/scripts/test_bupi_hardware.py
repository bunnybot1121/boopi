#!/usr/bin/env python3
"""
===============================================================================
BUPI ROBOT HARDWARE TEST HARNESS & AI MISSION RUNNER
===============================================================================
Tests all sensors (HC-SR04, PIR, MPU6050) and actuators (TB6612, Dual N20)
connected to the ESP32 over either:
  1. USB Serial (COM3 @ 115200 baud)
  2. Wireless Wi-Fi WebSockets (ws://0.0.0.0:8767)

Features:
  - Live Telemetry HUD: Real-time 20Hz sensor stream reader.
  - Direct Actuator Test: Keystroke motor pulses with auto-stop.
  - Safety Cutoff Verification: Tests <=15cm collision barrier & >35° tilt.
  - Autonomous Boopi AI Execution: Natural language mission parsing and execution.
===============================================================================
"""

import os
import sys
import time
import json
import threading
import argparse
import asyncio

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

try:
    import serial
    import serial.tools.list_ports
    HAS_SERIAL = True
except ImportError:
    HAS_SERIAL = False

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

try:
    from voice_bundle.voice_service import VoiceService
    HAS_VOICE = True
except Exception:
    HAS_VOICE = False

from planner.instruction_decomposer import InstructionDecomposer


def find_esp32_port() -> str:
    """Auto-detects USB CP210x or CH340 COM port on Windows."""
    if not HAS_SERIAL:
        return "COM3"
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        desc = (p.description or "").lower()
        if "cp210" in desc or "ch340" in desc or "usb-to-uart" in desc or "silicon labs" in desc:
            return p.device
    return "COM3"


class BupiHardwareTester:
    def __init__(self, port: str = "COM3", baud: int = 115200, use_ws: bool = False, ws_port: int = 8767):
        self.port = port
        self.baud = baud
        self.use_ws = use_ws
        self.ws_port = ws_port
        self.ser = None
        self.running = True
        self.lock = threading.Lock()
        
        # WebSocket server state
        self.ws_clients = set()
        self.ws_loop = None
        
        # Latest telemetry cache
        self.latest_telemetry = {
            "distance_cm": 200.0,
            "pir": 0,
            "pitch": 0.0,
            "roll": 0.0,
            "heading": 0.0,
            "obstacle": False,
            "moving": False
        }
        self.safety_events = []
        self.decomposer = InstructionDecomposer()

    def connect(self) -> bool:
        if self.use_ws:
            return self._start_ws_server()
        return self._connect_serial()

    def _connect_serial(self) -> bool:
        if not HAS_SERIAL:
            print("[Error] pyserial library is not installed.")
            return False
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            print(f"[Connected] Successfully opened {self.port} at {self.baud} baud.")
            time.sleep(1.0)
            t = threading.Thread(target=self._reader_loop, daemon=True)
            t.start()
            return True
        except serial.SerialException as e:
            if "PermissionError" in str(e) or "Access is denied" in str(e):
                print(f"\n[Port Locked] Could not open {self.port} because it is currently open in another program!")
                print("💡 FIX:")
                print("   1. Open Arduino IDE.")
                print("   2. Close the Serial Monitor tab/window (click the 'X' icon).")
                print("   3. Re-run: python scripts/test_bupi_hardware.py\n")
                print("   OR run in wireless Wi-Fi mode:")
                print("   python scripts/test_bupi_hardware.py --ws\n")
            else:
                print(f"[Connection Failed] Could not open {self.port}: {e}")
            return False
        except Exception as e:
            print(f"[Connection Failed] {e}")
            return False

    def _start_ws_server(self) -> bool:
        if not HAS_WEBSOCKETS:
            print("[Error] python websockets library is not installed.")
            return False

        print(f"[WebSocket Server] Starting wireless hub on 0.0.0.0:{self.ws_port}...")

        def run_ws_loop():
            self.ws_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.ws_loop)

            async def ws_handler(ws):
                client_ip = ws.remote_address[0] if ws.remote_address else "Unknown"
                print(f"\n[WebSocket] 🟢 ESP32 Robot Connected wirelessly from IP: {client_ip}!", flush=True)
                with self.lock:
                    self.ws_clients.add(ws)
                try:
                    async for message in ws:
                        line = message.strip()
                        if line.startswith("{") and line.endswith("}"):
                            try:
                                data = json.loads(line)
                                if data.get("type") == "telemetry":
                                    with self.lock:
                                        self.latest_telemetry.update(data)
                                elif data.get("type") == "announce":
                                    print(f"[WebSocket] 📡 Node Announcement: {data.get('device')} online!", flush=True)
                                elif "warning" in data or "safety_event" in data:
                                    with self.lock:
                                        self.safety_events.append(data)
                                    warn = data.get("warning") or data.get("safety_event")
                                    print(f"\n🚨 [ESP32 SAFETY CUTOFF] {warn} -> {data}", flush=True)
                            except Exception:
                                pass
                except Exception:
                    pass
                finally:
                    with self.lock:
                        if ws in self.ws_clients:
                            self.ws_clients.remove(ws)
                    print(f"[WebSocket] 🔴 ESP32 Disconnected ({client_ip}).", flush=True)

            async def main_coro():
                async with websockets.serve(ws_handler, "0.0.0.0", self.ws_port):
                    await asyncio.Future()

            self.ws_loop.run_until_complete(main_coro())

        t = threading.Thread(target=run_ws_loop, daemon=True)
        t.start()
        time.sleep(0.5)
        print(f"[WebSocket Ready] Listening for ESP32 at ws://192.168.0.106:{self.ws_port}")
        print("  (Make sure your ESP32 is powered on and connected to 'home' Wi-Fi)\n")
        return True

    def _reader_loop(self):
        while self.running and self.ser and self.ser.is_open:
            try:
                line = self.ser.readline().decode("utf-8", errors="ignore")
                if not line:
                    continue
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        data = json.loads(line)
                        if data.get("type") == "telemetry":
                            with self.lock:
                                self.latest_telemetry.update(data)
                        elif "warning" in data or "safety_event" in data:
                            with self.lock:
                                self.safety_events.append(data)
                            warn = data.get("warning") or data.get("safety_event")
                            print(f"\n🚨 [ESP32 SAFETY CUTOFF] {warn} -> {data}", flush=True)
                    except Exception:
                        pass
            except Exception:
                break

    def _reconnect_serial(self) -> bool:
        """Closes stale handle and re-opens serial connection."""
        try:
            if self.ser:
                try:
                    self.ser.close()
                except Exception:
                    pass
            time.sleep(0.4)
            self.ser = serial.Serial(self.port, self.baud, timeout=0.1)
            print(f"[Serial] 🔄 Reconnected to {self.port} successfully.")
            return True
        except Exception as e:
            print(f"[Serial Reconnect Failed] Could not re-open {self.port}: {e}")
            return False

    def send_cmd(self, action: str, speed: int = 180, duration_ms: int = 0):
        cmd_str = json.dumps({"action": action, "speed": speed, "duration_ms": duration_ms})
        if self.use_ws:
            with self.lock:
                clients = list(self.ws_clients)
            for ws in clients:
                try:
                    if self.ws_loop:
                        asyncio.run_coroutine_threadsafe(ws.send(cmd_str), self.ws_loop)
                except Exception as e:
                    print(f"[WS Send Error] {e}")
            return

        for attempt in range(2):
            try:
                if not self.ser or not self.ser.is_open:
                    if not self._reconnect_serial():
                        return
                self.ser.write((cmd_str + "\n").encode("utf-8"))
                self.ser.flush()
                return
            except Exception as e:
                if attempt == 0:
                    print(f"[Serial Info] Serial handle was reset ({e}). Auto-reconnecting...")
                    self._reconnect_serial()
                else:
                    print(f"[Serial Send Error] {e}")

    def send_raw(self, raw_str: str):
        if self.use_ws:
            self.send_cmd(raw_str)
            return

        for attempt in range(2):
            try:
                if not self.ser or not self.ser.is_open:
                    if not self._reconnect_serial():
                        return
                self.ser.write((raw_str + "\n").encode("utf-8"))
                self.ser.flush()
                return
            except Exception as e:
                if attempt == 0:
                    self._reconnect_serial()
                else:
                    print(f"[Serial Send Error] {e}")

    def monitor_hud(self, duration_sec: int = 20):
        """Displays a real-time HUD of all sensors."""
        print("\n" + "=" * 65)
        print("  📊 LIVE 20Hz SENSOR TELEMETRY HUD (Ctrl+C to exit)")
        print("=" * 65)
        start = time.time()
        try:
            while time.time() - start < duration_sec:
                with self.lock:
                    t = dict(self.latest_telemetry)
                dist = t.get("distance_cm", 999.0)
                pir = "🚨 MOTION" if t.get("pir") == 1 else "  QUIET "
                pitch = t.get("pitch", 0.0)
                roll = t.get("roll", 0.0)
                heading = t.get("heading", 0.0)
                obstacle = "⛔ OBSTACLE" if t.get("obstacle") else "  CLEAR   "
                moving = "🚗 MOVING " if t.get("moving") else "🛑 STOPPED"

                sys.stdout.write(
                    f"\r[Ultrasonic: {dist:5.1f}cm | {obstacle}] "
                    f"[PIR: {pir}] "
                    f"[IMU: P={pitch:5.1f}° R={roll:5.1f}° Yaw={heading:5.1f}°] "
                    f"[{moving}]"
                )
                sys.stdout.flush()
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        print("\n[HUD Finished]\n")

    def manual_actuator_test(self):
        """Interactive directional motor testing."""
        print("\n" + "=" * 65)
        print("  🎮 MANUAL ACTUATOR TEST CONSOLE")
        print("  Controls: [W]=Forward, [S]=Reverse, [A]=Left, [D]=Right, [Space]=Stop, [Q]=Quit")
        print("=" * 65)
        while True:
            choice = input("Enter command [w/s/a/d or 'move forward', 'stop', 'q']: ").strip().lower()
            if choice in ["q", "quit", "exit"]:
                break
            elif choice in ["w", "f", "forward", "move forward", "move_forward"]:
                print("➡️ Moving Forward (1000ms)...")
                self.send_cmd("MOVE_FORWARD", speed=255, duration_ms=1000)
                self.send_raw("w")
            elif choice in ["s", "b", "reverse", "backward", "move backward", "move_backward", "back"]:
                print("⬅️ Moving Reverse (1000ms)...")
                self.send_cmd("MOVE_BACKWARD", speed=255, duration_ms=1000)
                self.send_raw("s")
            elif choice in ["a", "l", "left", "turn left", "turn_left"]:
                print("↺ Turning Left (600ms)...")
                self.send_cmd("TURN_LEFT", speed=255, duration_ms=600)
                self.send_raw("a")
            elif choice in ["d", "r", "right", "turn right", "turn_right"]:
                print("↻ Turning Right (600ms)...")
                self.send_cmd("TURN_RIGHT", speed=255, duration_ms=600)
                self.send_raw("d")
            elif choice in [" ", "stop", "halt"]:
                print("🛑 Motors Stopped.")
                self.send_cmd("STOP")
            else:
                print(f"⚠️ Unknown input: '{choice}'. Use 'w' (forward), 's' (reverse), 'a' (left), 'd' (right), 'stop', or 'q'.")
            time.sleep(0.1)

    def test_safety_gate(self):
        """Tests the <=15cm obstacle cutoff and >35° tilt cutoff."""
        print("\n" + "=" * 65)
        print("  🛡️ HARDWARE SAFETY GATE TEST")
        print("  1. Place your hand < 15cm in front of HC-SR04 ultrasonic.")
        print("  2. Attempt to drive forward.")
        print("  3. ESP32 firmware should automatically refuse & halt!")
        print("=" * 65)

        input("Press Enter to check sensor values...")
        with self.lock:
            cur_dist = self.latest_telemetry.get("distance_cm", 999.0)
            cur_pitch = abs(self.latest_telemetry.get("pitch", 0.0))
            cur_roll = abs(self.latest_telemetry.get("roll", 0.0))

        print(f"Current Distance: {cur_dist:.1f} cm | Pitch: {cur_pitch:.1f}° | Roll: {cur_roll:.1f}°")

        if cur_dist <= 15.0:
            print("🚨 Obstacle detected at <= 15.0 cm! Attempting forward movement...")
            self.send_cmd("MOVE_FORWARD", speed=180, duration_ms=500)
            time.sleep(0.2)
            with self.lock:
                moving = self.latest_telemetry.get("moving", False)
            if not moving:
                print("✅ SAFETY PASS: ESP32 hardware blocked forward motor drive (Critical Obstacle Cutoff active)!")
            else:
                print("❌ SAFETY FAIL: Motors moved despite critical obstacle!")
        elif max(cur_pitch, cur_roll) > 35.0:
            print("🚨 Tilt detected at > 35.0°! Attempting forward movement...")
            self.send_cmd("MOVE_FORWARD", speed=180, duration_ms=500)
            time.sleep(0.2)
            with self.lock:
                moving = self.latest_telemetry.get("moving", False)
            if not moving:
                print("✅ SAFETY PASS: ESP32 hardware blocked motor drive (Tilt Hazard Cutoff active)!")
            else:
                print("❌ SAFETY FAIL: Motors moved despite tilt hazard!")
        else:
            print(f"Distance is {cur_dist:.1f} cm (> 15cm). Testing 300ms forward pulse...")
            self.send_cmd("MOVE_FORWARD", speed=160, duration_ms=300)
            time.sleep(0.4)
            print("Move executed. Try placing an obstacle < 15cm and re-run this test to see it blocked.")

    def run_boopi_ai_mission(self, user_instruction: str):
        """
        Takes ANY natural language instruction from the user, decomposes it with
        Boopi's AI, and executes closed-loop on the real hardware.
        """
        print("\n" + "=" * 65)
        print(f"  🧠 BOOPI AI DYNAMIC MISSION: '{user_instruction}'")
        print("=" * 65)

        print("[AI Planner] Analyzing natural language semantics...")
        plan = self.decomposer.decompose(user_instruction)
        print(f"[AI Plan] Policy: {plan.policy_type.value}")
        print(f"[AI Plan] Action: {plan.primary_action} @ {plan.speed_percent}% speed")
        action_name = plan.primary_action
        speed_val = int((plan.speed_percent / 100.0) * 255)
        if speed_val <= 0:
            speed_val = 255
        timeout = plan.timeout_seconds

        with self.lock:
            start_heading = self.latest_telemetry.get("heading", 0.0)

        print(f"\n[Executing] Sending '{action_name}' @ speed {speed_val} to ESP32. Monitoring stopping criteria...")
        self.send_cmd(action_name, speed=speed_val, duration_ms=0)

        start_time = time.time()
        condition_met = False

        try:
            while time.time() - start_time < timeout:
                elapsed = time.time() - start_time
                with self.lock:
                    telemetry = dict(self.latest_telemetry)

                # Compute dynamic angular heading offset for gyro turns
                curr_heading = telemetry.get("heading", 0.0)
                diff = abs(curr_heading - start_heading)
                if diff > 180.0:
                    diff = 360.0 - diff
                telemetry["heading_delta_deg"] = diff

                if plan.stop_condition.evaluate(telemetry, elapsed):
                    print(f"\n🎯 [Condition Met] {plan.stop_condition.description} satisfied!")
                    condition_met = True
                    break

                dist = telemetry.get("distance_cm", 999.0)
                pir = telemetry.get("pir", 0)
                sys.stdout.write(f"\r  Running [{elapsed:.1f}s/{timeout:.0f}s] Dist: {dist:5.1f}cm | PIR: {pir} | Heading: {curr_heading:5.1f}° (Δ{diff:4.1f}°)")
                sys.stdout.flush()
                time.sleep(0.05)

        finally:
            self.send_cmd("STOP")
            print("\n🛑 Motors Stopped.")

        with self.lock:
            final_telem = dict(self.latest_telemetry)

        print("\n" + "-" * 65)
        print("  📋 BOOPI MISSION REPORT")
        print("-" * 65)
        print(f"  Goal              : {user_instruction}")
        print(f"  Status            : {'SUCCESS' if condition_met else 'TIMEOUT'}")
        print(f"  Execution Time    : {time.time() - start_time:.2f} seconds")
        print(f"  Final Distance    : {final_telem.get('distance_cm', 0.0):.1f} cm")
        print(f"  PIR Sensor State  : {'MOTION DETECTED' if final_telem.get('pir') else 'QUIESCENT'}")
        print(f"  Final Heading     : {final_telem.get('heading', 0.0):.1f}°")
        print("-" * 65 + "\n")

        if HAS_VOICE:
            try:
                vs = VoiceService()
                msg = f"Mission {'successful' if condition_met else 'timed out'}. Obstacle at {final_telem.get('distance_cm', 0):.0f} centimeters. Heading {final_telem.get('heading', 0):.0f} degrees."
                threading.Thread(target=vs.speak, args=(msg,), daemon=True).start()
            except Exception:
                pass

    def run_voice_mission(self):
        """Listens for a spoken natural language command and runs the mission."""
        if not HAS_VOICE:
            print("[Voice Mode] VoiceService is not available on this system.")
            return
        print("\n" + "=" * 65)
        print("  🎙️ BOOPI VOICE MISSION CONSOLE")
        print("  Listening for speech on microphone (speak command now)...")
        print("=" * 65)
        try:
            vs = VoiceService()
            spoken = vs.listen(duration_limit=10)
            if spoken and spoken.strip():
                print(f"\n🗣️ Heard: '{spoken.strip()}'")
                self.run_boopi_ai_mission(spoken.strip())
            else:
                print("⚠️ No speech recognized. Please try again.")
        except Exception as e:
            print(f"[Voice Error] {e}")

    def close(self):
        self.running = False
        if self.ser and self.ser.is_open:
            self.send_cmd("STOP")
            self.ser.close()


def main():
    parser = argparse.ArgumentParser(description="BUPI Robot Hardware Test Harness")
    parser.add_argument("--port", type=str, default=find_esp32_port(), help="Serial COM port (default: auto)")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate (default: 115200)")
    parser.add_argument("--ws", action="store_true", help="Use wireless Wi-Fi WebSocket hub mode instead of USB Serial")
    parser.add_argument("--ws-port", type=int, default=8767, help="WebSocket port (default: 8767)")
    parser.add_argument("--mission", type=str, default="", help="Direct natural language mission to test")
    args = parser.parse_args()

    mode_label = f"Wireless Wi-Fi WebSockets on port {args.ws_port}" if args.ws else f"USB Serial on {args.port} @ {args.baud} baud"

    print("\n========================================================")
    print("      🤖 BUPI ROBOT HARDWARE TEST HARNESS")
    print(f"      Mode: {mode_label}")
    print("========================================================")

    tester = BupiHardwareTester(port=args.port, baud=args.baud, use_ws=args.ws, ws_port=args.ws_port)
    if not tester.connect():
        return

    if args.mission:
        tester.run_boopi_ai_mission(args.mission)
        tester.close()
        return

    try:
        while True:
            print("\nSelect a test mode:")
            print("  1. 📊 Live Sensor Telemetry HUD (Ultrasonic, PIR, MPU6050)")
            print("  2. 🎮 Manual Actuator Test (Forward, Reverse, Left, Right)")
            print("  3. 🛡️ Safety Cutoff Test (<=12cm barrier, >45° tilt)")
            print("  4. 🧠 Boopi AI Mission Test (Type Natural Language Instruction)")
            print("  5. 🎙️ Boopi Voice Mission Test (Speak into Microphone)")
            print("  6. 🔄 Run ESP32 Motor Wakeup Pulse")
            print("  7. 🚪 Exit")

            choice = input("\nEnter choice [1-7 or natural language mission]: ").strip()
            if choice == "1":
                tester.monitor_hud(duration_sec=20)
            elif choice == "2":
                tester.manual_actuator_test()
            elif choice == "3":
                tester.test_safety_gate()
            elif choice == "4":
                mission_text = input("\nEnter instruction for Boopi (e.g. 'walk until an obstacle comes in front of you'): ").strip()
                if mission_text:
                    tester.run_boopi_ai_mission(mission_text)
            elif choice == "5":
                tester.run_voice_mission()
            elif choice == "6":
                print("Triggering ESP32 hardware wakeup test...")
                tester.send_cmd("MOVE_FORWARD", speed=255, duration_ms=300)
                time.sleep(0.5)
                tester.send_cmd("MOVE_BACKWARD", speed=255, duration_ms=300)
            elif choice in ["7", "exit", "quit", "q"]:
                break
            elif any(w in choice.lower() for w in ["move", "walk", "forward", "backward", "reverse", "turn", "scan", "human", "patrol"]):
                print(f"💡 Detected natural language mission: '{choice}'")
                tester.run_boopi_ai_mission(choice)
            else:
                print(f"⚠️ Unrecognized choice: '{choice}'. Enter 1-7 or type a natural language mission.")
    finally:
        tester.close()
        print("\nTest harness closed.")


if __name__ == "__main__":
    main()
