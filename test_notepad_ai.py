import sys, os, time
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), 'assistant', '.env'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'assistant'))
from PyQt6.QtWidgets import QApplication
from brain.ai_brain import AIThread
from PyQt6.QtCore import QCoreApplication

app = QCoreApplication(sys.argv)
ai = AIThread()

def on_chunk(text):
    print("CHUNK:", text)

def on_notepad(text):
    print("NOTEPAD:", text)

def on_ready(text):
    print("READY:", text)
    app.quit()

ai.response_chunk.connect(on_chunk)
ai.notepad_insert.connect(on_notepad)
ai.response_ready.connect(on_ready)

ai.ask("Write a short prompt for an AI image generator to make a cute dog.")

app.exec()
