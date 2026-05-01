import sys
import os
import time

# Append assistant to path
sys.path.append(os.path.join(os.path.dirname(__file__), "assistant"))

from PyQt6.QtCore import QCoreApplication
from assistant.voice.listener import ListenerThread

app = QCoreApplication(sys.argv)

listener = ListenerThread()

def on_transcription(text):
    print(f"Heard: {text}")
    app.quit()

def on_error(err):
    print(f"Error: {err}")
    app.quit()

listener.transcription_ready.connect(on_transcription)
listener.error_occurred.connect(on_error)

print("Starting listener...")
listener.start()

# Keep alive for 10 seconds, then exit
import threading
def timeout():
    time.sleep(10)
    print("Test timed out.")
    app.quit()
threading.Thread(target=timeout, daemon=True).start()

app.exec()
