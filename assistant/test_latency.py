import time
import sys
import os
from dotenv import load_dotenv
load_dotenv()

# Set environment variable so PyQt doesn't complain
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QCoreApplication
from brain.ai_brain import AIThread

app = QCoreApplication(sys.argv)
ai = AIThread()

start_time = 0
first_chunk_time = None

def on_started(emotion):
    print(f"[{time.time() - start_time:.2f}s] Emotion determined: {emotion}")

def on_chunk(text):
    global first_chunk_time
    if first_chunk_time is None:
        first_chunk_time = time.time()
        print(f"[{first_chunk_time - start_time:.2f}s] First chunk received (Time to First Byte): {text}")
    else:
        print(f"[{time.time() - start_time:.2f}s] Chunk: {text}")

def on_ready(text):
    print(f"[{time.time() - start_time:.2f}s] Full response generated.")
    app.quit()

def on_error(err):
    print(f"Error: {err}")
    app.quit()

ai.response_started.connect(on_started)
ai.response_chunk.connect(on_chunk)
ai.response_ready.connect(on_ready)
ai.error_occurred.connect(on_error)

start_time = time.time()
print(f"[0.00s] Sending request to AI...")
ai.ask("Please summarize this for me, write a long text.")

app.exec()
