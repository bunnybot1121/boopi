import os
import sys
import time

sys.path.insert(0, os.path.abspath("."))
import config
from brain.ai_brain import AIThread
from PyQt6.QtCore import QCoreApplication

app = QCoreApplication([])

ai = AIThread()

received_started = []
received_chunks = []

def on_started(tag):
    print(f"AI Response Started: emotion=[{tag}] in {time.time()-t0:.2f}s")
    received_started.append(tag)

def on_chunk(txt):
    print(f"AI Chunk in {time.time()-t0:.2f}s: {txt}")
    received_chunks.append(txt)
    app.quit()

ai.response_started.connect(on_started)
ai.response_chunk.connect(on_chunk)

time.sleep(1.0)
print("\n--- Sending ask('How are you?') ---")
t0 = time.time()
ai.ask("How are you?")

from PyQt6.QtCore import QTimer
QTimer.singleShot(8000, lambda: (print("Timeout!"), app.quit()))

app.exec()
print(f"Total time: {time.time()-t0:.2f}s")
print(f"Chunks received: {len(received_chunks)}")
