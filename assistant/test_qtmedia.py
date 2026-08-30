import sys
import time
from PyQt6.QtCore import QCoreApplication, QUrl, QTimer
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
import os
import subprocess

app = QCoreApplication(sys.argv)

# Use existing test_out.mp3


player = QMediaPlayer()
audio = QAudioOutput()
player.setAudioOutput(audio)

def on_status(status):
    print("Status:", status)
    if status == QMediaPlayer.MediaStatus.EndOfMedia:
        print("Done!")
        app.quit()

player.mediaStatusChanged.connect(on_status)

player.setSource(QUrl.fromLocalFile(os.path.abspath("test_out.mp3")))
player.play()
print("Playing...")

QTimer.singleShot(10000, app.quit) # failsafe

sys.exit(app.exec())
