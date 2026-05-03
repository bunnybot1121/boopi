import sys
import os
import re
import json
import threading
import faulthandler

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

from PyQt6.QtCore import QCoreApplication, QTimer, Qt

from state_manager import state_mgr
from voice.listener import ListenerThread
from brain.ai_brain import AIThread
from voice.speaker import SpeakerThread
from actions.action_engine import detect_and_run
from memory import user_memory
from event_bus import bus
from bupi_node_server import start_node_server, send_to_esp32

app = QCoreApplication(sys.argv)

# -------------------------------------------------------------
# Init Threads
# -------------------------------------------------------------
listener = ListenerThread()
ai = AIThread()
speaker = SpeakerThread()

conversation_mode = False

# -------------------------------------------------------------
# Init Hardware / ESP32 Bridge
# -------------------------------------------------------------
start_node_server()

# Setup a 12-minute Water Reminder
def remind_water():
    send_to_esp32("Reminder!", "Drink Water!")
    state_mgr.force("talking")
    speaker.say("Excuse me, have you drank any water recently? Please stay hydrated!")

water_timer = QTimer()
water_timer.setInterval(720000) # 12 minutes in milliseconds
water_timer.timeout.connect(remind_water)
water_timer.start()

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
    
    # Send state updates to the ESP32 LCD!
    if state == "listening":
        send_to_esp32("Bupi Status:", "Listening...")
    elif state == "thinking":
        send_to_esp32("Bupi Status:", "Thinking...")
    elif state == "talking":
        send_to_esp32("Bupi Status:", "Talking...")
    elif state == "idle":
        send_to_esp32("Bupi Status:", "Idling (Zzz)")

bus.state_changed.connect(on_global_state_changed)

def start_listening():
    if state_mgr.current == "idle":
        if not listener.isRunning():
            listener.start()
        else:
            listener.resume()

# -------------------------------------------------------------
# Wiring Listener
# -------------------------------------------------------------
listener.listening_started.connect(lambda: state_mgr.transition("listening"))
listener.listening_stopped.connect(lambda: state_mgr.transition("thinking"))
listener.error_occurred.connect(lambda e: (
    print(json.dumps({"type": "log", "message": f"[Listener Error] {e}"}), flush=True),
    state_mgr.force("error"),
    QTimer.singleShot(2000, lambda: state_mgr.force("idle"))
))

def on_transcription(text: str):
    global conversation_mode
    safe_text = text.encode('ascii', 'ignore').decode('ascii')
    print(f"From Python: [Heard] '{safe_text}'", flush=True)

    inactivity_timer.start()

    if state_mgr.current == "angry":
        state_mgr.force("happy")
        speaker.say("Yay! You finally talked to me again!")
        return

    if not text:
        state_mgr.transition("idle")
        QTimer.singleShot(1000, start_listening)
        return

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

    text = text.strip()
    
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
            QTimer.singleShot(1000, start_listening)
            return

    handled, response = detect_and_run(text)
    if handled:
        state_mgr.transition("talking")
        speaker.say(response)
        return

    ai.ask(text)

listener.transcription_ready.connect(on_transcription)

# -------------------------------------------------------------
# Wiring AI
# -------------------------------------------------------------
def on_ai_started(tag: str):
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
        "chilling", "waiting", "typing"
    ]
    if tag in valid_emotions:
        emotion = tag

    state_mgr.transition(emotion)
    
def on_ai_chunk(text: str):
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
    send_whatsapp_message(recipient, message)

ai.response_started.connect(on_ai_started)
ai.response_chunk.connect(on_ai_chunk)
ai.notepad_insert.connect(on_ai_notepad)
ai.notepad_clear.connect(on_ai_notepad_clear)
ai.notepad_title.connect(on_ai_notepad_title)
ai.whatsapp_send.connect(on_ai_whatsapp_send)
ai.error_occurred.connect(lambda e: (
    print(json.dumps({"type": "log", "message": f"[AI Error] {e}"}), flush=True),
    state_mgr.force("error"),
    QTimer.singleShot(2000, lambda: state_mgr.force("idle"))
))

# -------------------------------------------------------------
# Wiring Speaker
# -------------------------------------------------------------
def on_speech_finished():
    state_mgr.transition("idle")
    QTimer.singleShot(1000, start_listening)

speaker.speech_finished.connect(on_speech_finished)
speaker.error_occurred.connect(lambda e: (
    print(json.dumps({"type": "log", "message": f"[TTS Error] {e}"}), flush=True),
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
            elif cmd == "test_ask":
                text = req.get("text", "")
                if listener.isRunning():
                    listener.pause()
                ai.ask(text)
        except Exception:
            pass

threading.Thread(target=stdin_listener, daemon=True).start()

# -------------------------------------------------------------
# Startup greeting sequence
# -------------------------------------------------------------
from datetime import datetime

def startup_sequence():
    user_name = user_memory.get("user_name", "Chintu")
    hour = datetime.now().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 17 else "Good evening"
    state_mgr.force("startup")
    
    # Open notepad and provide summary
    print(json.dumps({"type": "command", "value": "open_notepad"}), flush=True)
    on_ai_notepad_title("Notifications Summary")
    on_ai_notepad_clear()
    
    mock_notes = (
        "📧 Emails (3 Unread)\n"
        " - Client: \"Feedback on the latest design draft.\"\n"
        " - GitHub: \"Pull request #42 has been merged.\"\n"
        " - Newsletter: \"Weekly tech insights and news.\"\n\n"
        "💼 LinkedIn (2 Notifications)\n"
        " - John Doe endorsed you for Python.\n"
        " - You appeared in 12 searches this week.\n\n"
        "💬 WhatsApp (2 Unread)\n"
        " - Mom: \"Call me when you are free!\"\n"
        " - Group Chat: \"Lunch plans for tomorrow?\"\n"
    )
    on_ai_notepad(mock_notes)

    welcome_speech = f"Hi {user_name}, I have some notifications and I have summarized what you have got. I also checked your LinkedIn and WhatsApp and gave you a quick summary of all the stuff."
    speaker.say(welcome_speech)
    speaker.speech_finished.connect(
        lambda: state_mgr.force("idle"),
        Qt.ConnectionType.SingleShotConnection if hasattr(Qt, 'ConnectionType') else 1
    )

QTimer.singleShot(800, startup_sequence)

def shutdown():
    listener.stop()
    listener.wait(2000)
    speaker.quit()
    speaker.wait(2000)
    ai.quit()
    ai.wait(2000)

app.aboutToQuit.connect(shutdown)

sys.exit(app.exec())
