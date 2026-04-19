import sys
import time
from PyQt6.QtCore import QCoreApplication

app = QCoreApplication(sys.argv)
from test_speaker3 import SpeakerThread

s = SpeakerThread()
print("Starting initial speech...")
s.say("Hello world")

def next_speech():
    print("Starting second speech...")
    s.say("Are you there?")

def third_speech():
    print("Starting third speech...")
    s.say("Testing the crash...")
    s.speech_finished.connect(app.quit)

import threading
threading.Timer(5.0, next_speech).start()
threading.Timer(10.0, third_speech).start()

sys.exit(app.exec())
