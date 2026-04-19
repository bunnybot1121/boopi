import os
import sys
import time
import subprocess
from PyQt6.QtCore import QThread, pyqtSignal

class FFmpegAudio:
    _process = None

    @staticmethod
    def play(path):
        FFmpegAudio.stop()
        abs_path = os.path.abspath(path)
        print(f"From Python: [TTS] Playing audio from {abs_path}...", flush=True)
        try:
            FFmpegAudio._process = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", abs_path],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            print(f"From Python: [TTS] Audio player error: {e}", flush=True)
        
    @staticmethod
    def is_playing():
        if FFmpegAudio._process:
            return FFmpegAudio._process.poll() is None
        return False
        
    @staticmethod
    def stop():
        if FFmpegAudio._process and FFmpegAudio._process.poll() is None:
            try:
                FFmpegAudio._process.terminate()
                FFmpegAudio._process.wait(timeout=1.0)
            except Exception:
                pass
        FFmpegAudio._process = None

class SpeakerThread(QThread):
    speech_started  = pyqtSignal()
    speech_finished = pyqtSignal()
    error_occurred  = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._text = ""
        self._interrupted = False

    def say(self, text: str):
        if not text or not text.strip():
            self.speech_finished.emit()
            return
        
        if self.isRunning():
            self.interrupt()
            self.wait(2000)
        self._text = text
        self._interrupted = False
        self.start()

    def interrupt(self):
        self._interrupted = True
        FFmpegAudio.stop()

    def run(self):
        try:
            if self._interrupted:
                return

            self.speech_started.emit()
            
            temp_file = "temp_speech.mp3"
            voice = "en-US-AnaNeural"
            
            # Generate audio synchronously using edge-tts CLI tool
            subprocess.run(
                ["edge-tts", "--text", self._text, "--voice", voice, "--write-media", temp_file],
                creationflags=subprocess.CREATE_NO_WINDOW,
                check=True
            )

            if self._interrupted:
                return

            # Keep a tiny delay to ensure file is flushed to disk
            time.sleep(0.1)

            # Play audio
            FFmpegAudio.play(temp_file)
            
            # Wait for playback to finish
            while FFmpegAudio.is_playing() and not self._interrupted:
                time.sleep(0.1)

            # Cleanup
            FFmpegAudio.stop()
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

            if not self._interrupted:
                self.speech_finished.emit()

        except Exception as e:
            self.error_occurred.emit(str(e))
