import sys
import os
import re
import json
import threading
import faulthandler

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from dotenv import load_dotenv
load_dotenv()

faulthandler.enable()
faulthandler.enable()

from logger import crash_log

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

try:
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message
    mqtt_client.connect("localhost", 1883, 60)
    mqtt_client.loop_start()
except Exception as e:
    print(f"[Mode 1] Failed to start MQTT: {e}", flush=True)

def publish_to_mode2(text):
    print(f"[Mode 1] Forwarding to Mode 2: '{text}'", flush=True)
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
                    'powershell -Command "Get-CimInstance Win32_Process -Filter \\"Name = \'python.exe\' AND CommandLine LIKE \'%run_mode2.py%\'\\" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"',
                    shell=True,
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
        log_file = open(log_path, "a", encoding="utf-8")
        log_file.write(f"\n--- Spawned at {datetime.now()} ---\n")
        log_file.flush()
        mode2_process = subprocess.Popen([py_exe, "-u", script_path], stdout=log_file, stderr=subprocess.STDOUT, close_fds=True)
    except Exception as e:
        print(f"[Mode 1] Failed to spawn Mode 2 process: {e}", flush=True)

def auto_update_local_ip():
    import socket
    import re
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        current_ip = s.getsockname()[0]
        s.close()
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
    
    # Common names for Bupi
    bupi_names = ["bupi", "boopi", "boopy", "buppi", "boopie", "bupis", "boopis", "bobi", "bobby", "boby"]
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
# Inactivity Timer
# -------------------------------------------------------------
inactivity_timer = QTimer()
inactivity_timer.setInterval(60000) # 60 seconds
inactivity_timer.setSingleShot(True)

def make_angry():
    state_mgr.force("angry")
    # Complain about being ignored instead of running
    speaker.say("Why are you not talking to me?")

inactivity_timer.timeout.connect(make_angry)
inactivity_timer.start()

# IPC state observer
def on_global_state_changed(state: str):
    print(json.dumps({"type": "state", "value": state}), flush=True)
    if state == "idle":
        inactivity_timer.start()
    else:
        inactivity_timer.stop()

bus.state_changed.connect(on_global_state_changed)

def start_listening():
    if state_mgr.current == "idle":
        if not listener.isRunning():
            listener.start()
        else:
            was_paused = getattr(listener, "_paused", False)
            listener.resume()
            if not was_paused:
                state_mgr.transition("listening")

# -------------------------------------------------------------
# Wiring Listener
# -------------------------------------------------------------
def on_listening_started():
    state_mgr.transition("listening")

listener.listening_started.connect(on_listening_started)
listener.listening_stopped.connect(lambda: state_mgr.transition("thinking"))
listener.error_occurred.connect(lambda e: (
    print(json.dumps({"type": "log", "message": f"[Listener Error] {e}"}), flush=True),
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
    global conversation_mode
    global instruction_queue
    global mode2_active
    
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
        QTimer.singleShot(300, start_listening)
        return

    # Clear pending tasks if the user interrupts with a new command
    instruction_queue.clear()

    if re.search(r"\b(exit|quit|goodbye|bye bupi)\b", text, re.I):
        conversation_mode = False
        speaker.say("Goodbye! See you next time.")
        QTimer.singleShot(2500, app.quit)
        return

    if re.search(r"\b(stop|stop listening|okay let's stop it|stop it|that's all)\b", text, re.I):
        if conversation_mode:
            conversation_mode = False
            state_mgr.transition("talking")
            speaker.say("Okay, I'll be here if you need me.")
            return

    # Mode 2 explicit toggles
    if re.search(r"\b(?:shift|switch|change|enable|toggle|open|go)\s*(?:to|2|two)?\s*mode\s*(?:2|two|to|too)\b", text, re.I) or re.search(r"\bmode\s*(?:2|two|to|too)\b", text, re.I):
        mode2_active = True
        print(json.dumps({"type": "mode_changed", "value": 2}), flush=True)
        state_mgr.transition("talking")
        speaker.say("Shifting to Mode 2. Robotic orchestration enabled.")
        return

    if re.search(r"\b(?:shift|switch|change|enable|toggle|open|go)\s*(?:to|2|two)?\s*mode\s*(?:1|one|won)\b", text, re.I) or re.search(r"\bmode\s*(?:1|one|won)\b", text, re.I):
        mode2_active = False
        print(json.dumps({"type": "mode_changed", "value": 1}), flush=True)
        state_mgr.transition("talking")
        speaker.say("Shifting to Mode 1. Conversation mode enabled.")
        return

    
    wake_words = r"\b(boopy|boopie|puppy|poopy|bupi|boupi|boby|booby)\b"
    
    if not conversation_mode:
        if re.search(wake_words, text, re.I):
            conversation_mode = True
            cleaned = re.sub(wake_words, "", text, flags=re.I).strip()
            # Strip leading punctuation/commas that might break regex anchors
            cleaned = re.sub(r"^[^\w]+", "", cleaned)
            if len(cleaned) < 2 or re.match(r"^[^\w]*$", cleaned):
                state_mgr.transition("talking")
                import random
                speaker.say(random.choice(["Yes?", "I'm here.", "How can I help?"]))
                return
            text = cleaned
        else:
            state_mgr.transition("idle")
            QTimer.singleShot(300, start_listening)
            return

    if mode2_active:
        # Route to Mode 2 completely
        publish_to_mode2(text)
    else:
        # Route to Mode 1
        ai.ask(text)

listener.transcription_ready.connect(on_transcription)

# -------------------------------------------------------------
# Wiring AI
# -------------------------------------------------------------
last_ai_response = ""

def on_ai_started(tag: str):
    global last_ai_response
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
    setattr(listener, "is_speaking", False)
    if instruction_queue:
        state_mgr.transition("idle")
        # Give a slight delay before triggering the next task so it feels natural
        QTimer.singleShot(400, process_next_instruction)
    else:
        global last_ai_response
        sentiment_state = analyze_sentiment(last_ai_response)
        if sentiment_state and sentiment_state != "idle":
            state_mgr.transition(sentiment_state)
            # Hold the sentiment face for 2.5 seconds before returning to idle
            QTimer.singleShot(2500, lambda: (
                state_mgr.transition("idle"),
                QTimer.singleShot(300, start_listening)
            ))
        else:
            state_mgr.transition("idle")
            QTimer.singleShot(300, start_listening)

speaker.speech_started.connect(lambda: setattr(listener, "is_speaking", True))
speaker.speech_finished.connect(on_speech_finished)
speaker.error_occurred.connect(lambda e: (
    print(json.dumps({"type": "log", "message": f"[TTS Error] {e}"}), flush=True),
    setattr(listener, "is_speaking", False),
    state_mgr.force("idle")
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
                    mqtt_client.publish("bupi/internal/estop", json.dumps({"command": "STOP_ALL"}))
                    send_to_esp32("STOP_ALL")
                except Exception as ex:
                    print(f"E-Stop broadcast error: {ex}", flush=True)
                speaker.say("Emergency stop activated. All hardware motors halted.")
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
    print(json.dumps({"type": "mode_changed", "value": 1}), flush=True)
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

    welcome_speech = f"Hi {user_name}, I have some notifications and I have summarized what you have got. I also checked your LinkedIn and WhatsApp and gave you a quick summary of all the stuff."
    speaker.say(welcome_speech)
    def on_startup_finished():
        state_mgr.force("idle")
        QTimer.singleShot(300, start_listening)

    speaker.speech_finished.connect(
        on_startup_finished,
        Qt.ConnectionType.SingleShotConnection if hasattr(Qt, 'ConnectionType') else 1
    )

if "--lab-mode" not in sys.argv:
    QTimer.singleShot(800, startup_sequence)

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
