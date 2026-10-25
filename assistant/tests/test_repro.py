import sys
import time
import os
from PyQt6.QtCore import QCoreApplication

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
app = QCoreApplication(sys.argv)

from brain.ai_brain import AIThread

ai = AIThread()
print("Initialized AIThread, waiting 1s...")
time.sleep(1)

print("Calling ai.interrupt()...")
ai.interrupt()

print("Calling ai.ask('What are you doing?')...")
ai.ask("What are you doing?")

def on_started(e):
    print(f"AI STARTED with emotion: {e}", flush=True)

def on_chunk(c):
    print(f"AI CHUNK: {c}", flush=True)

def on_ready(r):
    print(f"AI READY: {r}", flush=True)
    app.quit()

ai.response_started.connect(on_started)
ai.response_chunk.connect(on_chunk)
ai.response_ready.connect(on_ready)

from PyQt6.QtCore import QTimer
QTimer.singleShot(15000, lambda: (print("TIMEOUT 15s reached!"), app.quit()))

sys.exit(app.exec())
