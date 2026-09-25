import sys
import os
import re
import json
import threading
import time
import traceback
import faulthandler

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

from dotenv import load_dotenv
load_dotenv()

faulthandler.enable()

from logger import crash_log

def _global_excepthook(exc_type, exc_value, exc_traceback):
    err_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    crash_log(f"CRITICAL UNHANDLED EXCEPTION:\n{err_msg}")
    print(f"[Engine Fatal Error]\n{err_msg}", file=sys.stderr, flush=True)

sys.excepthook = _global_excepthook

crash_log("=== Python engine starting ===")

# Thread-safe print: prevents concurrent stdout pipe writes from crashing Python 3.14
_print_lock = threading.Lock()
_original_print = print
def _safe_print(*args, **kwargs):
    with _print_lock:
        _original_print(*args, **kwargs)
import builtins
builtins.print = _safe_print

from PyQt6.QtCore import QCoreApplication, QTimer, Qt, QObject, pyqtSignal

from state_manager import state_mgr
from voice.listener import ListenerThread
from brain.ai_brain import AIThread
from voice.speaker import SpeakerThread
from actions.action_engine import detect_and_run, ActionEngine
from brain.db_manager import db_manager
from brain.activity_monitor import ActivityMonitorService
from brain.daily_briefing_service import DailyBriefingService
from event_bus import bus
from bupi_node_server import start_node_server, send_to_esp32

app = QCoreApplication(sys.argv)

# -------------------------------------------------------------
# Init Threads & Services
# -------------------------------------------------------------
listener = ListenerThread()
ai = AIThread()
speaker = SpeakerThread()

action_engine = ActionEngine()
activity_monitor = ActivityMonitorService()
activity_monitor.start()

daily_briefing = DailyBriefingService(ai, speaker)

conversation_mode = True
mode2_active = False
on_hold = False

# Check command line flags for initial mode
if "--mode" in sys.argv:
    try:
        m_idx = sys.argv.index("--mode")
        if m_idx + 1 < len(sys.argv):
            boot_m = int(sys.argv[m_idx + 1])
            mode2_active = (boot_m == 2)
    except Exception:
        pass
elif "--robot" in sys.argv or "--mode2" in sys.argv:
    mode2_active = True

def set_active_mode(target_mode: int, notify_speaker: bool = True):
    global mode2_active
    mode_num = 2 if target_mode == 2 else 1
    mode2_active = (mode_num == 2)
    print(f"[Mode Manager] Active Mode set to Mode {mode_num} (Robotic: {mode2_active})", flush=True)
    print(json.dumps({"type": "mode_changed", "value": mode_num}), flush=True)
    print(json.dumps({"type": "mode-changed", "value": mode_num}), flush=True)
    if notify_speaker:
        state_mgr.transition("talking")
        if mode_num == 2:
            speaker.say("Shifting to Mode 2. Robotic orchestration enabled.")
        else:
            speaker.say("Shifting to Mode 1. Conversation mode enabled.")

# -------------------------------------------------------------
# Mode 2 MQTT Bridge
# -------------------------------------------------------------
import paho.mqtt.client as mqtt

class Mode2Bridge(QObject):
    do_speak = pyqtSignal(str)

m2_bridge = Mode2Bridge()
m2_bridge.do_speak.connect(lambda t: (state_mgr.transition("talking"), speaker.say(t)))

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="Mode1_App")

def on_mqtt_connect(client, userdata, flags, reason_code, properties):
    print(f"[Mode 1] Connected to Mode 2 MQTT Bridge with result code {reason_code}", flush=True)
    client.subscribe("bupi/internal/tts")
    client.subscribe("bupi/nodes/announce")
    client.subscribe("bupi/nodes/heartbeat")
    client.subscribe("bupi/sensors/#")
    client.subscribe("footmo2/#")
    client.subscribe("bwe/esp32/write/#")
    client.subscribe("bwe/esp32/stats")

def on_mqtt_message(client, userdata, msg):
    topic = msg.topic
    if topic.startswith("bwe/esp32/write/"):
        try:
            pin = int(topic.split("/")[-1])
            payload = json.loads(msg.payload.decode('utf-8'))
            val = float(payload.get("value", 0.0))
            print(json.dumps({"type": "bwe_pin_write", "pin": pin, "val": val}), flush=True)
        except Exception:
            pass
    elif topic == "bwe/esp32/stats":
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            print(json.dumps({"type": "bwe_esp32_stats", "value": payload}), flush=True)
        except Exception:
            pass
    elif topic == "bupi/internal/tts":
        try:
            global mode2_waiting_response
            mode2_waiting_response = False
            payload = json.loads(msg.payload.decode())
            text = payload.get("text", "")
            if text:
                print(f"[Mode 1] Received TTS from Mode 2: {text}", flush=True)
                m2_bridge.do_speak.emit(text)
        except Exception as e:
            print(f"[Mode 1] Error parsing Mode 2 TTS: {e}")
    elif msg.topic in ["bupi/nodes/announce", "bupi/nodes/heartbeat"]:
        try:
            payload = json.loads(msg.payload.decode())
            node_id = payload.get("client_id", "MQTT_Unknown")
            device = payload.get("device", "MQTT Node")
            ip = payload.get("ip", "N/A")
            capabilities = payload.get("capabilities", ["MQTT"])
            tasks = payload.get("tasks", ["General MQTT Client"])
            
            from bupi_node_server import register_node, update_node_heartbeat
            if msg.topic == "bupi/nodes/announce":
                register_node(node_id, ip, "MQTT", device, capabilities, tasks)
            else:
                update_node_heartbeat(node_id)
        except Exception as e:
            print(f"[Mode 1] Error parsing MQTT Node status/heartbeat: {e}", flush=True)
    elif msg.topic.startswith("bupi/sensors/") or msg.topic.startswith("footmo2/"):
        try:
            from bupi_node_server import register_node, update_node_heartbeat
            node_id = "BUPI_ESP32_MQ2_NODE1"
            device = "MQ2 Gas & LCD Display"
            if msg.topic.startswith("footmo2/"):
                parts = msg.topic.split("/")
                if len(parts) >= 2:
                    node_id = parts[1]
                    device = f"ESP32 Node ({parts[1]})"
            register_node(node_id, "192.168.0.107", "MQTT", device, ["Display", "Sensor"], ["Telemetry", "Display"])
            update_node_heartbeat(node_id)

            # Persist directly into SQLite nodes table so Mode 1 always has real-time freshness
            import sqlite3, time
            db_file = os.path.join(os.path.dirname(__file__), "bupi_telemetry.db")
            conn = sqlite3.connect(db_file)
            c = conn.cursor()
            c.execute("""
                INSERT INTO nodes (client_id, device_name, ip_address, capabilities, last_heartbeat, status)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(client_id) DO UPDATE SET
                    last_heartbeat=excluded.last_heartbeat,
                    status='online'
            """, (node_id, device, "192.168.0.107", '["Display", "Sensor"]', time.time(), "online"))
            conn.commit()
            conn.close()
        except Exception:
            pass

try:
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message
    mqtt_client.connect("localhost", 1883, 60)
    mqtt_client.loop_start()
except Exception as e:
    print(f"[Mode 1] Failed to start MQTT: {e}", flush=True)

mode2_waiting_response = False
mode2_utterance_epoch = 0

def publish_to_mode2(text):
    global mode2_waiting_response, mode2_utterance_epoch
    mode2_waiting_response = True
    mode2_utterance_epoch += 1
    print(f"[Mode 1] Forwarding to Mode 2 (epoch {mode2_utterance_epoch}): '{text}'", flush=True)
    mqtt_client.publish("bupi/internal/utterance", json.dumps({"text": text}))

# -------------------------------------------------------------
# Init Hardware / ESP32 Bridge
# -------------------------------------------------------------
import subprocess
mode2_process = None

def start_mode2_process():
    global mode2_process
    try:
        from datetime import datetime
        
        # Clean up any previously orphaned run_mode2.py processes to avoid MQTT client conflicts on Windows
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ['powershell', '-NoProfile', '-Command', 
                     "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*run_mode2.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

        venv_py = os.path.join(os.path.dirname(__file__), "venv312", "Scripts", "python.exe")
        py_exe = venv_py if os.path.exists(venv_py) else sys.executable
        script_path = os.path.join(os.path.dirname(__file__), "run_mode2.py")
        print(f"[Mode 1] Spawning Mode 2 background process: {py_exe} {script_path}", flush=True)
        log_path = os.path.join(os.path.dirname(__file__), "mode2_log.txt")
        # Rotate mode2_log.txt if it exceeds 5MB to prevent disk saturation
        if os.path.exists(log_path) and os.path.getsize(log_path) > 5 * 1024 * 1024:
            try:
                with open(log_path, "w", encoding="utf-8") as f_rot:
                    f_rot.write(f"--- Log rotated at {datetime.now()} ---\n")
            except Exception:
                pass
        log_file = open(log_path, "a", encoding="utf-8")
        log_file.write(f"\n--- Spawned at {datetime.now()} ---\n")
        sub_env = os.environ.copy()
        sub_env["OPENBLAS_NUM_THREADS"] = "1"
        sub_env["MKL_NUM_THREADS"] = "1"
        sub_env["NUMEXPR_NUM_THREADS"] = "1"
        sub_env["OMP_NUM_THREADS"] = "1"
        mode2_process = subprocess.Popen([py_exe, "-u", script_path], stdout=log_file, stderr=subprocess.STDOUT, env=sub_env)
    except Exception as e:
        print(f"[Mode 1] Failed to spawn Mode 2 process: {e}", flush=True)

def auto_update_local_ip():
    import socket
    import re
    
    try:
        # Check if Windows Mobile Hotspot (192.168.137.x) is active on this host
        all_ips = socket.gethostbyname_ex(socket.gethostname())[2]
        hotspot_ips = [ip for ip in all_ips if ip.startswith("192.168.137.")]
        if hotspot_ips:
            current_ip = hotspot_ips[0]
        else:
            current_ip = "192.168.137.1"
    except Exception:
        current_ip = "127.0.0.1"
        
    if current_ip == "127.0.0.1" or not current_ip:
        return
        
    print(f"[IP Auto-Config] Detected current PC IP: {current_ip}", flush=True)
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    files_to_update = [
        os.path.join(base_dir, "hardware_rules.md"),
        os.path.join(base_dir, "esp32_bupi_client.ino"),
        os.path.join(base_dir, "esp32_hive_display.ino"),
        os.path.join(base_dir, "workspace", "BupiNode", "BupiNode.ino")
    ]
    
    ip_pattern = re.compile(r'(const\s+char\s*\*\s*(?:mqtt_server|websocket_server)\s*=\s*")[0-9.]+(";?)')
    
    for file_path in files_to_update:
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                match = ip_pattern.search(content)
                if match:
                    full_match = match.group(0)
                    inner_match = re.search(r'"([0-9.]+)"', full_match)
                    if inner_match:
                        old_ip = inner_match.group(1)
                        if old_ip != current_ip:
                            new_content = ip_pattern.sub(rf'\g<1>{current_ip}\g<2>', content)
                            with open(file_path, "w", encoding="utf-8") as f:
                                f.write(new_content)
                            print(f"[IP Auto-Config] Updated {os.path.basename(file_path)}: {old_ip} -> {current_ip}", flush=True)
            except Exception as e:
                print(f"[IP Auto-Config Warning] Failed to update {file_path}: {e}", flush=True)

auto_update_local_ip()
start_node_server()
start_mode2_process()

# Periodic check for offline ESP32 nodes
from bupi_node_server import check_node_timeouts
node_timeout_timer = QTimer()
node_timeout_timer.setInterval(5000) # Every 5 seconds
node_timeout_timer.timeout.connect(check_node_timeouts)
node_timeout_timer.start()

# Setup a 12-minute Water Reminder
def remind_water():
    send_to_esp32("Reminder!", "Drink Water!")
    state_mgr.force("talking")
    speaker.say("Excuse me, have you drank any water recently? Please stay hydrated!")

water_timer = QTimer()
water_timer.setInterval(720000) # 12 minutes in milliseconds
water_timer.timeout.connect(remind_water)
water_timer.start()

def check_reminders():
    try:
        import time
        now = time.time()
        pending = db_manager.get_pending_reminders(now)
        for rem in pending:
            db_manager.mark_reminder_notified(rem["id"])
            username = db_manager.get_preference("username", "Chintu")
            print(f"[Reminder] Triggering reminder notification: '{rem['text']}'", flush=True)
            
            # Speak it
            state_mgr.force("happy")
            speaker.say(f"{username}, you have a reminder: {rem['text']}")
            
            # Show on notepad
            sync_packet = {
                "notepad_text": f"REMINDER ALERT:\n\nTime: {time.strftime('%Y-%m-%d %I:%M %p', time.localtime(rem['trigger_time']))}\n\nTask: {rem['text']}",
                "notepad_title": "Reminder Alert",
                "notepad_clear": False
            }
            print(json.dumps({"type": "notepad", "value": sync_packet}), flush=True)
    except Exception as e:
        print(f"[Reminder Error] {e}", flush=True)
        
reminder_timer = QTimer()
reminder_timer.setInterval(5000) # Check every 5 seconds
reminder_timer.timeout.connect(check_reminders)
reminder_timer.start()

def check_hold_or_resume(text: str) -> bool:
    global on_hold
    if not text:
        return False
    clean = text.lower().replace(".", "").replace(",", "").replace("?", "").replace("!", "").strip()
    words = clean.split()
    
    # Common names for Prag / Bupi
    bupi_names = [
        "prag", "pragg", "prak", "prog", "prague", "praag", "plag", "brag", "frag",
        "bupi", "boopi", "boopy", "buppi", "boopie", "bupis", "boopis", "bobi", "bobby", "boby",
        "bot", "robot"
    ]
    has_bupi = any(w in words for w in bupi_names)
    
    # Hold keywords/phrases
    hold_phrases = [
        "hold a second", "hold on a second", "hold on", 
        "hold on for a second", "hold on a minute", "hold a minute",
        "hold on a moment", "hold a moment", "wait a second", "wait a moment",
        "pause please", "please pause", "stop taking instructions",
        "pause taking instructions", "pause instructions",
        "hold instructions"
    ]
    has_hold = any(w in words for w in ["hold", "pause"])
    
    is_hold_cmd = any(phrase in clean for phrase in hold_phrases) or (has_bupi and has_hold)
    
    # Resume keywords/phrases
    resume_phrases = [
        "can we continue", "can we resume", "please continue", "please resume",
        "let's continue", "let's resume", "continue taking instructions",
        "continue instructions", "resume instructions", "resume taking instructions",
        "start taking instructions", "start instructions"
    ]
    has_resume = any(w in words for w in ["continue", "resume"])
    
    is_resume_cmd = any(phrase in clean for phrase in resume_phrases) or (has_bupi and has_resume) or (clean in ["continue", "resume"])
    
    if on_hold:
        if is_resume_cmd:
            print("[HoldManager] Matched resume command. Resuming...", flush=True)
            on_hold = False
            username = "User"
            try:
                username = db_manager.get_preference("username", "User")
            except Exception:
                pass
            resume_speech = f"Welcome back, {username}! I'm ready for your instructions."
            state_mgr.force("happy")
            speaker.say(resume_speech)
            return True
        else:
            print(f"[HoldManager] On hold: ignoring input: '{text}'", flush=True)
            state_mgr.force("chilling")
            return True
    else:
        if is_hold_cmd:
            print("[HoldManager] Matched hold command. Pausing...", flush=True)
            on_hold = True
            hold_speech = "Sure, I'll hold on! Say 'Bupi continue' when you're ready."
            state_mgr.force("chilling")
            speaker.say(hold_speech)
            return True
            
    return False

# -------------------------------------------------------------
# Inactivity Timer (Gentle idle check - 10 minutes)
# -------------------------------------------------------------
inactivity_timer = QTimer()
inactivity_timer.setInterval(600000) # 10 minutes idle
inactivity_timer.setSingleShot(True)

def make_angry():
    if conversation_mode and not on_hold:
        state_mgr.transition("chilling")

inactivity_timer.timeout.connect(make_angry)

# IPC state observer
def on_global_state_changed(state: str):
    print(json.dumps({"type": "state", "value": state}), flush=True)
    if state == "idle":
        inactivity_timer.start()
    else:
        inactivity_timer.stop()

bus.state_changed.connect(on_global_state_changed)

def start_listening():
    if not listener.isRunning():
        listener.start()
    else:
        listener.resume()

# Thinking Watchdog: Guarantees Bupi NEVER gets stuck in thinking state
thinking_watchdog = QTimer()
thinking_watchdog.setInterval(25000) # 25 seconds max thinking timeout (allows local LLM / multi-step planning)
thinking_watchdog.setSingleShot(True)

def on_thinking_timeout():
    if state_mgr.current == "thinking":
        print("[Watchdog] ⚠️ Thinking state timed out after 25s. Auto-recovering to idle...", flush=True)
        try:
            ai.interrupt()
        except Exception:
            pass
        state_mgr.transition("idle")
        start_listening()

thinking_watchdog.timeout.connect(on_thinking_timeout)

# -------------------------------------------------------------
# Wiring Listener
# -------------------------------------------------------------
def on_listening_started():
    if state_mgr.current == "thinking":
        # Don't let mic noise or echo interrupt STT transcription or active thinking
        return
    thinking_watchdog.stop()
    if state_mgr.current == "talking":
        print("[Barge-In] User started speaking while assistant talking. Stopping speech...", flush=True)
        try:
            speaker.stop()
        except Exception:
            pass
    state_mgr.transition("listening")

def on_listening_stopped():
    state_mgr.transition("thinking")
    thinking_watchdog.start()

listener.listening_started.connect(on_listening_started)
listener.listening_stopped.connect(on_listening_stopped)
listener.error_occurred.connect(lambda e: (
    print(json.dumps({"type": "log", "message": f"[Listener Error] {e}"}), flush=True),
    thinking_watchdog.stop(),
    state_mgr.force("error"),
    QTimer.singleShot(2000, lambda: state_mgr.force("idle"))
))

instruction_queue = []

def process_next_instruction():
    if not instruction_queue:
        return
        
    task = instruction_queue.pop(0)
    print(f"From Python: [Task Queue] Executing: {task}", flush=True)
    
    try:
        action_engine.execute_action(task)
    except Exception as e:
        print(f"From Python: [Orchestrator] Action '{task}' failed: {e}", flush=True)
        # Clear remaining tasks because a step failed
        instruction_queue.clear()
        # Feed error back to AI for self-correction
        ai.ask(f"[System Error in Orchestrator]: The action '{task}' failed with error: {e}. Please apologize and output a new [ACTION: ...] to try an alternative approach.")
        return
        
    # Give a small delay before next task
    QTimer.singleShot(500, process_next_instruction)

def on_transcription(text: str):
    try:
        _handle_transcription(text)
    except Exception as e:
        err_str = traceback.format_exc()
        print(f"[Main Error in on_transcription] {err_str}", flush=True)
        crash_log(f"Exception in on_transcription:\n{err_str}")
        try:
            state_mgr.transition("idle")
        except Exception:
            pass

def _handle_transcription(text: str):
    global conversation_mode
    global instruction_queue
    global mode2_active
    
    thinking_watchdog.stop()
    
    if text:
        text = text.strip()
        if check_hold_or_resume(text):
            return
        # Send what we heard to the thought cloud so the user gets instant visual confirmation of the STT
        print(json.dumps({"type": "speech_text", "value": f"Heard: \"{text}\""}), flush=True)
        
    safe_text = text.encode('ascii', 'ignore').decode('ascii') if text else ""
    print(f"From Python: [Heard] '{safe_text}'", flush=True)

    inactivity_timer.start()

    if state_mgr.current == "angry":
        state_mgr.force("happy")
        speaker.say("Yay! You finally talked to me again!")
        return

    if not text:
        state_mgr.transition("idle")
        return

    # Clear pending tasks if the user interrupts with a new command
    instruction_queue.clear()

    # ONLY explicit, clear application exit phrases will terminate the app
    if re.search(r"^\s*(?:exit\s*app|close\s*app|quit\s*app|shutdown\s*app|exit\s*application|close\s*application|shutdown\s*system|close\s*boopi|exit\s*boopi)\b[\.!?]?\s*$", text, re.I):
        conversation_mode = False
        speaker.say("Goodbye! Closing Bupi companion.")
        QTimer.singleShot(2500, app.quit)
        return

    # ONLY explicit conversation stop phrases toggle conversation mode off (NOT motor stop / halt commands!)
    if re.search(r"\b(stop listening|stop conversation|go to sleep|sleep now|take a rest|that's all|that is all|okay let's stop it|goodbye|bye)\b", text, re.I):
        if conversation_mode:
            conversation_mode = False
            state_mgr.transition("talking")
            speaker.say("Okay, I'll be here if you need me.")
            return

    # Mode 2 explicit toggles (Generic & dynamic natural phrasing)
    if re.search(r"\b(?:shift|switch|change|enable|toggle|open|go|turn|activate|start|enter)?\s*(?:in|into|to)?\s*(?:mode\s*(?:to\s*)?(?:2|two|too)|robotic\s*mode|robot\s*mode)\b", text, re.I) or re.search(r"^\s*mode\s*(?:2|two)\s*$", text, re.I):
        set_active_mode(2)
        return

    if re.search(r"\b(?:shift|switch|change|enable|toggle|open|go|turn|activate|start|enter)?\s*(?:in|into|to)?\s*(?:mode\s*(?:to\s*)?(?:1|one|won)|conversational\s*mode|conversation\s*mode|chat\s*mode)\b", text, re.I) or re.search(r"^\s*mode\s*(?:1|one)\s*$", text, re.I):
        set_active_mode(1)
        return

    wake_words = r"\b(prag|pragg|prak|prog|prague|praag|plag|brag|frag|boopi|boopy|boopie|bupi|bupie|boupi|boby|booby|puppy|poopy)\b"
    bot_addressing = r"\b(the bot|the robot|bot|robot)\b"
    has_wake = bool(re.search(wake_words, text, re.I))
    has_bot = bool(re.search(bot_addressing, text, re.I))

    # Direct autonomous mission, relative distance move, or emergency stop (active in Mode 2)
    is_direct_mission_or_estop = bool(
        re.search(r"(\d+(?:\.\d+)?)\s*(?:cm|centimeter|centimeters|cms|m|meter|meters|inch|inches|mm|millimeters)\b", text, re.I) or
        re.search(r"\b(scan the room|scan room|scan around|scan|sweep|search the room|search room|patrol|explore|emergency stop|e-stop|stop motors|halt|stop moving|stop driving|stop the robot|brake)\b", text, re.I)
    )

    from agents.router_agent import router
    fast_intent = router.quick_regex_classify(text)
    has_robot_intent = (fast_intent is not None)

    if not conversation_mode:
        if has_wake or has_bot or (mode2_active and (is_direct_mission_or_estop or has_robot_intent)):
            conversation_mode = True
            cleaned = re.sub(wake_words, "", text, flags=re.I).strip()
            # If user said e.g. "robot, move forward", also strip "robot" if at start (never strip when robot number is specified)
            cleaned = re.sub(r"^(?:the\s+)?(?:bot|robot)(?!\s*(?:1|2|one|two|01|02))\b[:,]?\s*", "", cleaned, flags=re.I).strip()
            # Strip leading punctuation/commas
            cleaned = re.sub(r"^[^\w]+", "", cleaned)
            if len(cleaned) < 2 or re.match(r"^[^\w]*$", cleaned) or cleaned.lower() in ["hey", "hi", "hello", "ok", "okay"]:
                state_mgr.transition("talking")
                import random
                speaker.say(random.choice(["Yes?", "I'm here, ready.", "How can I help you?"]))
                return
            text = cleaned
            fast_intent = router.quick_regex_classify(text)
        else:
            state_mgr.transition("idle")
            return
    else:
        # Already in conversation mode: strip wake word if repeated
        if has_wake:
            cleaned = re.sub(wake_words, "", text, flags=re.I).strip()
            cleaned = re.sub(r"^[^\w]+", "", cleaned)
            if cleaned:
                text = cleaned
                fast_intent = router.quick_regex_classify(text)

    # =============================================================
    # MODE 1: STRICT CONVERSATIONAL ISOLATION
    # =============================================================
    if not mode2_active:
        # Check if the user is giving a physical hardware / robotics instruction
        is_robot_command = False
        if fast_intent:
            itype = fast_intent.get("type")
            if itype in ["autonomous_mission", "abort_mission", "edge_avoid_mode",
                         "hardware_intent", "sensor_query", "world_state_query",
                         "nodes_query", "mission_report_query"]:
                is_robot_command = True

        direct_robot_actions = [
            r"\b(move forward|move backward|move back|turn left|turn right|spin|rotate|drive forward|drive back|drive reverse|advance|step forward|step back)\b",
            r"\b(stop motors|halt|emergency stop|brake|stop moving|stop driving|stop the robot|e-stop)\b",
            r"\b(patrol|explore|scan the room|scan room|find the human|find human|find person|locate human|search room|approach|move towards)\b",
            r"\b(turn on relay|turn off relay|check gas|check smoke|front distance|ultrasonic reading)\b",
            r"\b(points?\s+of\s+the\s+room|mark\s+out|give\s+(?:the\s+)?readings|take\s+readings|environmental\s+survey|survey\s+the\s+room)\b",
            r"\b(?:bot\s*[12]|bupi\s*[12]|scout|specialist)\b"
        ]
        if any(re.search(pat, text, re.I) for pat in direct_robot_actions):
            is_robot_command = True

        if is_robot_command:
            print(f"[Mode 1 Auto-Bridge] 🤖 Robotics command detected: '{text}' -> Seamlessly activating Mode 2 and executing!", flush=True)
            set_active_mode(2, notify_speaker=False)
            # Fall through into Mode 2 robotic orchestration below!
        else:
            # In Mode 1: All conversational queries, chat, desktop actions, notes go to conversational AI companion!
            ai.ask(text)
            return

    # =============================================================
    # MODE 2: AUTONOMOUS ROBOTICS & HARDWARE ORCHESTRATION
    # =============================================================
    try:
        if fast_intent:
            itype = fast_intent.get("type")
            payload = fast_intent.get("payload", {})
            print(f"[Mode 2 Fast-Pass] ⚡ Matched: {itype} -> {payload}", flush=True)

            if itype == "autonomous_mission":
                mission_text = payload.get("mission", text)
                try:
                    from agents.autonomous_goal_agent import goal_agent
                    # Wire direct speech callback for instant low-latency speech feedback
                    goal_agent._tts_callback = lambda t: m2_bridge.do_speak.emit(t)
                    state_mgr.force("thinking")
                    res = goal_agent.start_mission(mission_text)
                    print(f"[Mode 2 Mission] {res}", flush=True)
                    speaker.say(res)
                except Exception as me:
                    speaker.say(f"Could not start autonomous mission: {me}")
                return

            elif itype == "abort_mission":
                try:
                    from agents.autonomous_goal_agent import goal_agent
                    res = goal_agent.stop_mission()
                    state_mgr.force("cautious")
                    speaker.say("Mission stopped. All motors halted.")
                except Exception as me:
                    speaker.say("Failed to abort mission.")
                return

            elif itype == "mission_report_query":
                try:
                    from agents.autonomous_goal_agent import goal_agent
                    latest = goal_agent.get_latest_mission_report()
                    if latest:
                        m_name = latest.get("mission_name", "Mission")
                        summary = latest.get("summary", "")
                        status = latest.get("status", "COMPLETED")
                        duration = latest.get("duration_seconds", 0)
                        spoken = f"Last mission {m_name} finished in {duration} seconds with status {status}. {summary}"
                        state_mgr.force("talking")
                        speaker.say(spoken)
                        # Switch to missions panel in Bupi Hub
                        print(json.dumps({"type": "command", "value": "open_notepad"}), flush=True)
                        print(json.dumps({"type": "notepad_switch_tab", "value": "panel-missions"}), flush=True)
                        print(json.dumps({"type": "mission_report", "value": latest}), flush=True)
                    else:
                        state_mgr.force("talking")
                        speaker.say("No mission reports recorded yet. Say 'Boopi, find the human' to start a mission.")
                except Exception as me:
                    speaker.say(f"Could not retrieve mission report: {me}")
                return

            elif itype == "edge_avoid_mode":
                enabled = payload.get("enabled", True)
                payload_json = json.dumps({"action": "auto_avoid", "enabled": enabled})
                mqtt_client.publish("bupi/actuators/motors/cmd/json", payload_json)
                if enabled:
                    state_mgr.force("excited")
                    speaker.say("Edge obstacle avoidance enabled. Navigating on ESP32.")
                else:
                    state_mgr.force("idle")
                    speaker.say("Obstacle avoidance disabled. Standby.")
                return

            elif itype == "hardware_intent":
                dev = payload.get("device")
                action = payload.get("action")
                direction = payload.get("direction", "")
                
                if dev == "motors":
                    target_bot = payload.get("robot_id") or "bupi_01"
                    from actions.hardware_tools import control_motors
                    raw_fn = getattr(control_motors, "func", getattr(control_motors, "_run", control_motors))
                    if direction == "stop":
                        try:
                            from agents.autonomous_goal_agent import goal_agent
                            if goal_agent.is_running:
                                goal_agent.stop_mission(reason="Voice Stop")
                        except Exception:
                            pass
                        raw_fn(direction="stop", speed=0, duration_seconds=0, robot_id=target_bot)
                        mqtt_client.publish("bupi/actuators/motors/cmd/json", json.dumps({"action": "auto_avoid", "enabled": False}))
                        state_mgr.force("cautious")
                        speaker.say("Emergency stop triggered. Motors halted.")
                    else:
                        res = raw_fn(direction=direction, speed=255, duration_seconds=1.5, robot_id=target_bot)
                        print(f"[Mode 2 Fast Motor Exec] {res}", flush=True)
                        state_mgr.force("excited")
                        target_phrase = " (both bots)" if target_bot in ["all", "both", "fleet", "bots"] else (f" ({target_bot})" if target_bot != "bupi_01" else "")
                        speaker.say(f"Driving {direction}{target_phrase}.")
                    return
                elif dev == "relay":
                    state_str = "ON" if action == "ON" else "OFF"
                    mqtt_client.publish("bupi/hardware/relay_1/set", state_str)
                    state_mgr.force("talking")
                    speaker.say(f"Relay turned {action.lower()}.")
                    return

            elif itype == "sensor_query":
                sensor_id = payload.get("sensor_id", "mq2")
                try:
                    from actions.hardware_tools import read_sensor_status
                    raw_fn = getattr(read_sensor_status, "func", read_sensor_status)
                    res_str = raw_fn(sensor_id)
                    res_json = json.loads(res_str)
                    status = res_json.get("status", "UNKNOWN")
                    raw_val = res_json.get("raw_value")
                    bot_name = "Bot 2" if res_json.get("robot_id") == "bupi_02" else "Bot 1"

                    if sensor_id in ["distance", "ultrasonic", "hcsr04"]:
                        if status == "OFFLINE" or raw_val is None:
                            spoken = "The ultrasonic distance sensor is currently offline. Please ensure the robot is powered on and connected."
                        elif raw_val < 35.0:
                            spoken = f"Yes, an obstacle is detected {raw_val:.1f} centimeters directly in front of {bot_name}."
                        else:
                            spoken = f"No obstacles detected. The path ahead is clear with {raw_val:.1f} centimeters of clearance."
                    elif sensor_id in ["mq2", "gas", "smoke"]:
                        if status == "OFFLINE" or raw_val is None:
                            spoken = "The MQ-2 gas sensor is currently offline. Please ensure Bot 2 is connected."
                        elif raw_val > 300.0:
                            spoken = f"Warning! Elevated gas or smoke detected on Bot 2 at {raw_val:.1f} ppm."
                        else:
                            spoken = f"Air quality is clean and safe. Gas level is {raw_val:.1f} ppm."
                    elif sensor_id in ["temp", "temperature", "dht"]:
                        if status == "OFFLINE" or raw_val is None:
                            spoken = "The temperature sensor is currently offline."
                        else:
                            spoken = f"The ambient temperature is {raw_val:.1f} degrees Celsius, status is {status}."
                    elif sensor_id in ["humidity"]:
                        if status == "OFFLINE" or raw_val is None:
                            spoken = "The humidity sensor is currently offline."
                        else:
                            spoken = f"The ambient humidity is {raw_val:.1f} percent, status is {status}."
                    else:
                        spoken = f"The {sensor_id} reading is {raw_val}, status is {status}."

                    state_mgr.force("talking")
                    speaker.say(spoken)
                except Exception as e:
                    state_mgr.force("talking")
                    speaker.say(f"Could not read {sensor_id}: {e}")
                return

            elif itype == "world_state_query":
                try:
                    from core.safety_validator import get_current_world_state
                    ws = get_current_world_state()
                    gas_st = ws.get("gas", "UNKNOWN")
                    dist_st = ws.get("distance", "CLEAR")
                    state_mgr.force("talking")
                    speaker.say(f"World state: gas is {gas_st}, front path is {dist_st}.")
                except Exception as e:
                    speaker.say(f"World state check failed: {e}")
                return

            elif itype == "nodes_query":
                try:
                    from actions.hardware_tools import get_connected_nodes
                    raw_fn = getattr(get_connected_nodes, "func", get_connected_nodes)
                    res_str = raw_fn()
                    res_json = json.loads(res_str)
                    nodes_list = res_json.get("connected_nodes", [])
                    state_mgr.force("talking")
                    online_nodes = [n for n in nodes_list if n.get("status") == "ONLINE"]
                    if online_nodes:
                        first_dev = online_nodes[0].get("device_name", "ESP32")
                        first_ip = online_nodes[0].get("ip_address", "")
                        ip_phrase = f" at IP {first_ip}" if first_ip and first_ip != "unknown" else ""
                        speaker.say(f"Yes! An ESP32 is online and connected. {first_dev}{ip_phrase}.")
                    elif nodes_list:
                        first_dev = nodes_list[0].get("device_name", "ESP32")
                        speaker.say(f"The ESP32 node {first_dev} is registered, but it hasn't sent a heartbeat recently.")
                    else:
                        speaker.say("No ESP32 nodes are currently connected on the network.")
                except Exception as e:
                    speaker.say(f"Node query failed: {e}")
                return
    except Exception as router_err:
        print(f"[Mode 2 Router Error] {router_err}", flush=True)

    # In Mode 2: Forward non-deterministic queries to Mode 2 background runner via MQTT
    publish_to_mode2(text)
    epoch_snap = mode2_utterance_epoch

    # Watchdog: Monitors Mode 2 background execution without causing conversational collisions
    def mode2_fallback_watchdog(snap):
        time.sleep(15.0)
        if mode2_waiting_response and mode2_utterance_epoch == snap:
            print(f"[Mode 2 Watchdog] Mode 2 background process took >15s to process: '{text}'.", flush=True)
            # Do NOT invoke conversational AI companion (prevents double-talking, overlapping speech, and garbage output)

    threading.Thread(target=mode2_fallback_watchdog, args=(epoch_snap,), daemon=True).start()

listener.transcription_ready.connect(on_transcription)

# -------------------------------------------------------------
# Wiring AI
# -------------------------------------------------------------
last_ai_response = ""

def on_ai_started(tag: str):
    global last_ai_response
    thinking_watchdog.stop()
    last_ai_response = ""
    emotion = "talking"
    
    if tag in ["sad", "error"]:
        tag = "angry"
    elif tag in ["happy1", "happy2", "happy mode", "smiling", "laughing"]:
        tag = "happy"
    elif tag in ["loading", "processing"]:
        tag = "thinking"
    elif tag in ["praise", "good"]:
        tag = "praise"
    elif tag in ["excited", "wow"]:
        tag = "excited"
    elif tag in ["lazy", "sleepy"]:
        tag = "idle"
        
    valid_emotions = [
        "idle", "happy", "angry", "error", "thinking", "listening", 
        "talking", "startup", "praise", "excited", "booting", 
        "chilling", "waiting", "typing", "concerned", "confused",
        "writing", "reading", "recording", "drinking_coffee",
        "cautious", "celebrating", "surprised"
    ]
    if tag in valid_emotions:
        emotion = tag

    state_mgr.transition(emotion)
    
def on_ai_chunk(text: str):
    global last_ai_response
    last_ai_response += " " + text
    speaker.say(text, interrupt=False)

def on_ai_notepad(text: str):
    print(json.dumps({"type": "notepad_insert", "value": text}), flush=True)

def on_ai_notepad_clear():
    print(json.dumps({"type": "notepad_clear"}), flush=True)

def on_ai_notepad_title(title: str):
    print(json.dumps({"type": "notepad_title", "value": title}), flush=True)

def on_ai_whatsapp_send(recipient: str, message: str):
    from actions.action_engine import send_whatsapp_message
    print(f"From Python: [AI Triggered Action] Sending to {recipient}...", flush=True)
    result = send_whatsapp_message(recipient, message)
    if result:
        if result.startswith("Error:"):
            print(f"From Python: [Automation Error] {result}", flush=True)
            ai.ask(f"[System Error]: {result}")
        else:
            state_mgr.force("talking")
            speaker.say(result)

def on_ai_email_send(recipient: str, subject: str, message: str):
    from actions.automation_agent import send_email_playwright
    print(f"From Python: [AI Triggered Action] Sending Email to {recipient}...", flush=True)
    result = send_email_playwright(recipient, subject, message)
    if result:
        if result.startswith("Error:"):
            print(f"From Python: [Automation Error] {result}", flush=True)
            ai.ask(f"[System Error]: {result}")
        else:
            state_mgr.force("talking")
            speaker.say(result)

def on_ai_linkedin_send(recipient: str, message: str):
    from actions.automation_agent import send_linkedin_playwright
    print(f"From Python: [AI Triggered Action] Sending LinkedIn to {recipient}...", flush=True)
    result = send_linkedin_playwright(recipient, message)
    if result:
        if result.startswith("Error:"):
            print(f"From Python: [Automation Error] {result}", flush=True)
            ai.ask(f"[System Error]: {result}")
        else:
            state_mgr.force("talking")
            speaker.say(result)

def on_ai_draw(url: str):
    print(json.dumps({"type": "draw", "value": url}), flush=True)

def on_ai_action(actions: list):
    global instruction_queue
    print(f"From Python: [AI Orchestrator] Received {len(actions)} actions: {actions}", flush=True)
    
    queued_actions = []
    for act in actions:
        # Run screen updates instantly for immediate visual feedback (don't wait for TTS to finish)
        if re.search(r"print|display|show", act, re.I) and "esp" in act.lower():
            print(f"From Python: [Fast Track] Executing instantly: {act}", flush=True)
            action_engine.execute_action(act)
        else:
            queued_actions.append(act)
            
    if queued_actions:
        instruction_queue.extend(queued_actions)
        # If not currently speaking/executing, start processing immediately
        if not speaker.isRunning() or state_mgr.current == "idle":
            QTimer.singleShot(500, process_next_instruction)

ai.response_started.connect(on_ai_started)
ai.response_chunk.connect(on_ai_chunk)
ai.notepad_insert.connect(on_ai_notepad)
ai.notepad_clear.connect(on_ai_notepad_clear)
ai.notepad_title.connect(on_ai_notepad_title)
ai.whatsapp_send.connect(on_ai_whatsapp_send)
ai.email_send.connect(on_ai_email_send)
ai.linkedin_send.connect(on_ai_linkedin_send)
ai.ai_draw.connect(on_ai_draw)
ai.ai_action.connect(on_ai_action)

def on_hardware_result(result: str):
    print(json.dumps({"type": "hardware_result", "value": result}), flush=True)

ai.hardware_result.connect(on_hardware_result)

ai.error_occurred.connect(lambda e: (
    print(json.dumps({"type": "log", "message": f"[AI Error] {e}"}), flush=True),
    state_mgr.force("error"),
    QTimer.singleShot(2000, lambda: state_mgr.force("idle"))
))

# -------------------------------------------------------------
# Wiring Speaker
# -------------------------------------------------------------
def analyze_sentiment(text: str) -> str:
    if not text:
        return "idle"
    text_lower = text.lower()
    
    # Check celebrating
    if any(w in text_lower for w in ["celebrate", "party", "hooray", "hurray", "cheers", "woohoo", "birthday"]) or any(e in text for e in ["🎉", "🥳", "🎈", "🎊", "✨"]):
        return "celebrating"
        
    # Check dancing (excited)
    if any(w in text_lower for w in ["dance", "excited", "thrilled", "ecstatic", "yay", "yippee", "cannot wait", "groove"]) or any(e in text for e in ["💃", "🕺", "🎶", "🎵"]):
        return "excited"
        
    # Check proud
    if any(w in text_lower for w in ["proud", "congrats", "congratulations", "achievement", "success", "bravo", "genius", "smart", "accomplished", "winner"]) or any(e in text for e in ["🏆", "🥇", "👑"]):
        return "praise"
        
    # Check waving
    if any(w in text_lower for w in ["wave", "hello", "hi", "hey", "welcome", "goodbye", "bye", "see ya"]) or "👋" in text:
        return "startup"
        
    # Check curious
    if any(w in text_lower for w in ["curious", "wonder", "question", "interesting", "fascinating", "hmm", "tell me more", "explore"]) or any(e in text for e in ["🔍", "🔎", "❓", "❔"]):
        return "surprised"
        
    # Check cautious
    if any(w in text_lower for w in ["careful", "caution", "warning", "unsafe", "watch out", "danger", "risk"]) or any(e in text for e in ["⚠️", "🚨"]):
        return "cautious"
        
    # Check happy
    if any(w in text_lower for w in ["smile", "happy", "laugh", "joy", "great", "wonderful", "awesome", "good", "glad", "pleasure"]) or any(e in text for e in [":)", ":-)", "😀", "😃", "😄", "😁", "😆", "😊"]):
        return "happy"
        
    return "idle"

def on_speech_finished():
    # Allow 350ms acoustic cooldown for speaker room echo to settle before unmuting VAD
    QTimer.singleShot(350, lambda: setattr(listener, "is_speaking", False))
    if instruction_queue:
        state_mgr.transition("idle")
        QTimer.singleShot(200, process_next_instruction)
    else:
        global last_ai_response
        sentiment_state = analyze_sentiment(last_ai_response)
        if sentiment_state and sentiment_state != "idle":
            state_mgr.transition(sentiment_state)
            # Re-arm listener immediately so user can speak right away with 0 delay!
            start_listening()
            # Return mascot face to idle after a brief natural 1.0s window if user hasn't spoken
            QTimer.singleShot(1000, lambda: (
                state_mgr.transition("idle") if state_mgr.current == sentiment_state else None
            ))
        else:
            state_mgr.transition("idle")
            start_listening()

speaker.speech_started.connect(lambda: (
    thinking_watchdog.stop(),
    setattr(listener, "is_speaking", True),
    state_mgr.force("talking")
))
speaker.speech_finished.connect(on_speech_finished)
speaker.error_occurred.connect(lambda e: (
    print(json.dumps({"type": "log", "message": f"[TTS Error] {e}"}), flush=True),
    setattr(listener, "is_speaking", False),
    state_mgr.force("idle"),
    start_listening()
))

# -------------------------------------------------------------
# IPC Listener (Stdin)
# -------------------------------------------------------------
from PyQt6.QtCore import QObject, pyqtSignal

class StdinBridge(QObject):
    do_start_listening = pyqtSignal()
    do_clear_memory = pyqtSignal()
    do_toggle_conversation = pyqtSignal()
    do_quit = pyqtSignal()
    do_process_hardware = pyqtSignal(str)
    do_flash_hardware = pyqtSignal(str)
    do_refresh_keys = pyqtSignal()

bridge = StdinBridge()

bridge.do_start_listening.connect(start_listening)

def _on_clear_memory():
    ai.clear_memory()
    speaker.say("Memory cleared.")

bridge.do_clear_memory.connect(_on_clear_memory)

def _on_toggle_conv():
    global conversation_mode
    conversation_mode = not conversation_mode
    
    # We must pause the mic listening before speaking
    was_running = listener.isRunning()
    if was_running:
        listener.pause()
        
    state_mgr.force("talking")
    
    if conversation_mode:
        speaker.say("Conversation mode enabled. I am listening to everything now.")
    else:
        speaker.say("Conversation mode disabled. You must say my name first.")

bridge.do_toggle_conversation.connect(_on_toggle_conv)
bridge.do_quit.connect(app.quit)
bridge.do_process_hardware.connect(ai.process_hardware)
bridge.do_flash_hardware.connect(ai.flash_hardware)
bridge.do_refresh_keys.connect(ai.check_api_keys)

def stdin_listener():
    for line in sys.stdin:
        try:
            req = json.loads(line)
            cmd = req.get("command")
            if cmd == "start_listening":
                bridge.do_start_listening.emit()
            elif cmd == "set_mode":
                target_m = int(req.get("mode", 1))
                speak_flag = req.get("speak", True)
                set_active_mode(target_m, notify_speaker=speak_flag)
            elif cmd == "get_mode":
                curr_m = 2 if mode2_active else 1
                print(json.dumps({"type": "mode_changed", "value": curr_m}), flush=True)
                print(json.dumps({"type": "mode-changed", "value": curr_m}), flush=True)
            elif cmd == "clear_memory":
                bridge.do_clear_memory.emit()
            elif cmd == "toggle_conversation":
                bridge.do_toggle_conversation.emit()
            elif cmd == "quit":
                bridge.do_quit.emit()
            elif cmd == "refresh_keys":
                bridge.do_refresh_keys.emit()
            elif cmd == "refresh_nodes":
                from bupi_node_server import broadcast_nodes
                broadcast_nodes()
            elif cmd == "test_ask":
                text = req.get("text", "")
                if check_hold_or_resume(text):
                    continue
                if listener.isRunning():
                    listener.pause()
                ai.ask(text)
            elif cmd == "trigger_briefing":
                threading.Thread(target=daily_briefing.generate_briefing, daemon=True).start()
            elif cmd == "pause_listener":
                if listener.isRunning():
                    listener.pause()
            elif cmd == "resume_listener":
                if listener.isRunning():
                    listener.resume()
            elif cmd == "process_hardware":
                code = req.get("code", "")
                bridge.do_process_hardware.emit(code)
            elif cmd == "flash_hardware":
                code = req.get("code", "")
                bridge.do_flash_hardware.emit(code)
            elif cmd == "bwe_pin_update":
                pin = req.get("pin")
                val = req.get("val")
                if pin is not None and val is not None:
                    mqtt_client.publish(f"bwe/simulator/write/{pin}", json.dumps({"value": val}))
            elif cmd == "estop":
                print("From Python: [EMERGENCY STOP] Triggering hardware E-Stop hard cut...", flush=True)
                try:
                    from agents.autonomous_goal_agent import goal_agent
                    if goal_agent.is_running:
                        goal_agent.stop_mission(reason="Emergency Stop")
                    mqtt_client.publish("bupi/internal/estop", json.dumps({"command": "STOP_ALL"}))
                    send_to_esp32("STOP_ALL")
                except Exception as ex:
                    print(f"E-Stop broadcast error: {ex}", flush=True)
                speaker.say("Emergency stop activated. All hardware motors halted.")
            elif cmd == "get_mission_history":
                try:
                    from agents.autonomous_goal_agent import goal_agent
                    history = goal_agent.get_mission_history(20)
                    print(json.dumps({"type": "mission_history", "value": history}), flush=True)
                except Exception as mhe:
                    print(f"[Mission History Error] {mhe}", flush=True)
            elif cmd == "get_mission_status":
                try:
                    from agents.autonomous_goal_agent import goal_agent
                    status = goal_agent.get_status()
                    print(json.dumps({"type": "mission_status", "value": status}), flush=True)
                except Exception as mse:
                    print(f"[Mission Status Error] {mse}", flush=True)
            elif cmd == "start_mission":
                goal = req.get("goal", "Find the human in the room")
                try:
                    from agents.autonomous_goal_agent import goal_agent
                    res = goal_agent.start_mission(goal)
                    print(f"[Main Mission] {res}", flush=True)
                except Exception as sme:
                    print(f"[Start Mission Error] {sme}", flush=True)
            elif cmd == "stop_mission":
                try:
                    from agents.autonomous_goal_agent import goal_agent
                    res = goal_agent.stop_mission(reason="User command via GUI")
                    print(f"[Main Mission] {res}", flush=True)
                except Exception as stme:
                    print(f"[Stop Mission Error] {stme}", flush=True)
            elif cmd == "search_components":
                query = req.get("query", "")
                def run_search():
                    try:
                        from services.knowledge_super_agent import KnowledgeSuperAgent
                        agent = KnowledgeSuperAgent()
                        results = agent.search_online_components(query)
                        print(json.dumps({"type": "online_search_results", "query": query, "results": results}), flush=True)
                    except Exception as e:
                        print(json.dumps({"type": "online_search_results", "query": query, "results": [], "error": str(e)}), flush=True)
                threading.Thread(target=run_search, daemon=True).start()
        except Exception:
            pass

threading.Thread(target=stdin_listener, daemon=True).start()

# -------------------------------------------------------------
# Startup greeting sequence
# -------------------------------------------------------------
from datetime import datetime

def _format_notifications_dashboard_fallback(gmail, github, linkedin):
    lines = []
    lines.append("✧ ══════════════════════════════════════ ✧")
    lines.append("         BUPI NOTIFICATION HUB")
    lines.append("✧ ══════════════════════════════════════ ✧\n")
    
    lines.append("📧 GOOGLE MAIL (GMAIL) INBOX")
    lines.append("──────────────────────────────────────────")
    if gmail and "not configured" not in gmail.lower() and "error" not in gmail.lower() and "no unread" not in gmail.lower() and "no primary" not in gmail.lower():
        lines.append(gmail)
    elif "no unread" in gmail.lower() or "no primary" in gmail.lower():
        lines.append("  No unread emails.")
    else:
        lines.append(f"  {gmail}")
    lines.append("")
    
    lines.append("🐙 GITHUB NOTIFICATIONS")
    lines.append("──────────────────────────────────────────")
    if github and "not configured" not in github.lower() and "error" not in github.lower() and "no unread" not in github.lower():
        lines.append(github)
    elif "no unread" in github.lower():
        lines.append("  You have not received any notifications from GitHub.")
    else:
        lines.append(f"  {github}")
    lines.append("")
    
    lines.append("💬 LINKEDIN NOTIFICATIONS")
    lines.append("──────────────────────────────────────────")
    if linkedin and "not configured" not in linkedin.lower() and "error" not in linkedin.lower() and "no recent" not in linkedin.lower() and "no unread" not in linkedin.lower():
        lines.append(linkedin)
    elif "no recent" in linkedin.lower() or "no unread" in linkedin.lower():
        lines.append("  You have not received any notifications from LinkedIn.")
    else:
        lines.append(f"  {linkedin}")
    lines.append("\n✧ ══════════════════════════════════════ ✧")
    lines.append("          Have a wonderful day! ✨")
    return "\n".join(lines)

def _fetch_real_notifications_async():
    try:
        # 1. Fetch Gmail (Fast)
        try:
            from actions.gmail_helper import get_unread_emails
            gmail_text = get_unread_emails()
        except Exception as ge:
            gmail_text = f"Error: {ge}"
        
        # 2. Fetch GitHub (Fast)
        try:
            from actions.github_helper import get_github_updates
            github_text = get_github_updates()
        except Exception as ghe:
            github_text = f"Error: {ghe}"

        # Intermediate display
        real_notes = _format_notifications_dashboard_fallback(gmail_text, github_text, "Syncing LinkedIn notifications... 🔄")
        print(json.dumps({"type": "notepad_clear"}), flush=True)
        print(json.dumps({"type": "notepad_insert", "value": real_notes}), flush=True)

        # 3. Fetch LinkedIn (Slower)
        try:
            from actions.automation_agent import AutomationAgent
            agent = AutomationAgent()
            linkedin_text = agent.fetch_linkedin_notifications()
        except Exception as le:
            linkedin_text = f"Error: {le}"
            
        formatted_notes = _format_notifications_dashboard_fallback(gmail_text, github_text, linkedin_text)
        
        print(json.dumps({"type": "notepad_clear"}), flush=True)
        print(json.dumps({"type": "notepad_insert", "value": formatted_notes}), flush=True)
        
    except Exception as e:
        print(f"[Notifications Error] {e}", flush=True)

def startup_sequence():
    user_name = db_manager.get_preference("username", "Chintu")
    hour = datetime.now().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    state_mgr.force("startup")
    
    # Open notepad and provide summary
    initial_mode = 2 if mode2_active else 1
    print(json.dumps({"type": "mode_changed", "value": initial_mode}), flush=True)
    print(json.dumps({"type": "mode-changed", "value": initial_mode}), flush=True)
    print(json.dumps({"type": "command", "value": "open_notepad"}), flush=True)
    on_ai_notepad_title("Notifications Summary")
    on_ai_notepad_clear()
    
    loading_text = (
        "✧ ══════════════════════════════════════ ✧\n"
        "         BUPI NOTIFICATION HUB\n"
        "✧ ══════════════════════════════════════ ✧\n\n"
        "  🔄 Syncing real-time notifications...\n"
        "  - Gmail Inbox\n"
        "  - GitHub Notifications\n"
        "  - LinkedIn Updates\n\n"
        "  Please wait a moment... ✨\n"
    )
    on_ai_notepad(loading_text)
    
    # Start background thread to fetch real notifications
    threading.Thread(target=_fetch_real_notifications_async, daemon=True).start()
    
    # Run key check asynchronously 5 seconds after boot
    QTimer.singleShot(5000, ai.check_api_keys)

    welcome_speech = f"Hey {user_name}! Prag is ready."
    speaker.say(welcome_speech)
    def on_startup_finished():
        state_mgr.force("idle")

    speaker.speech_finished.connect(
        on_startup_finished,
        Qt.ConnectionType.SingleShotConnection if hasattr(Qt, 'ConnectionType') else 1
    )
    
    # Arm listener immediately on startup so user NEVER has to wait through idleness
    QTimer.singleShot(300, start_listening)

if "--lab-mode" not in sys.argv:
    QTimer.singleShot(300, startup_sequence)

def shutdown():
    global mode2_process
    if mode2_process:
        print("[Mode 1] Terminating Mode 2 background process...", flush=True)
        try:
            mode2_process.terminate()
            mode2_process.wait(1000)
        except Exception:
            try:
                mode2_process.kill()
            except Exception:
                pass
    listener.stop()
    listener.wait(2000)
    speaker.quit()
    speaker.wait(2000)
    ai.quit()
    ai.wait(2000)
    try:
        activity_monitor.stop()
    except Exception:
        pass

app.aboutToQuit.connect(shutdown)

sys.exit(app.exec())
