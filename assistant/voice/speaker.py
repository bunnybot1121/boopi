import os
import time
import subprocess
import ctypes
from PyQt6.QtCore import QThread, pyqtSignal
import threading

# Crash-safe disk logger (imported from logger modules)
def _log(msg):
    try:
        from logger import crash_log
        crash_log(f"[Speaker] {msg}")
    except Exception:
        pass

import threading
import subprocess
import queue

class Win32Audio:
    _ffplay_proc = None
    _lock = threading.Lock()

    @staticmethod
    def play(path):
        Win32Audio.stop()
        abs_path = os.path.abspath(path)
        print(f"From Python: [TTS] Playing audio from {abs_path}...", flush=True)

        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE

        with Win32Audio._lock:
            Win32Audio._ffplay_proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", abs_path],
                startupinfo=info,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        
    @staticmethod
    def is_playing():
        with Win32Audio._lock:
            if Win32Audio._ffplay_proc is None:
                return False
            return Win32Audio._ffplay_proc.poll() is None
        
    @staticmethod
    def stop():
        with Win32Audio._lock:
            if Win32Audio._ffplay_proc is not None:
                if Win32Audio._ffplay_proc.poll() is None:
                    Win32Audio._ffplay_proc.terminate()
                Win32Audio._ffplay_proc = None

class SpeakerThread(QThread):
    speech_started  = pyqtSignal()
    speech_finished = pyqtSignal()
    error_occurred  = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._queue = queue.Queue()
        self._interrupted = False
        self.start() # Start immediately and stay alive

    def say(self, text: str):
        if not text or not text.strip():
            self.speech_finished.emit()
            return
        
        # Interrupt any ongoing speech
        self.interrupt()
        
        # Add the new speech request
        self._queue.put({"text": text})

    def interrupt(self):
        self._interrupted = True
        Win32Audio.stop()
        # Clear out any pending requests
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def quit(self):
        # Stop everything and inject poison pill to kill the thread
        self.interrupt()
        self._queue.put(None)

    def run(self):
        while True:
            try:
                item = self._queue.get()
                if item is None: # Exit signal
                    break
                
                text_to_say = item["text"]
                self._interrupted = False

                if self._interrupted:
                    continue

                self.speech_started.emit()
                
                temp_file = "temp_speech.mp3"
                voice = "en-US-AnaNeural"
                
                _log(f"Step 1: Starting edge-tts subprocess for: {text_to_say[:50]}")
                print(f"From Python: [TTS] Generating audio...", flush=True)
                
                flags = subprocess.CREATE_NO_WINDOW

                subprocess.run(
                    ["edge-tts", "--text", text_to_say, "--voice", voice, "--write-media", temp_file],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=flags,
                    check=True
                )
                _log("Step 2: edge-tts subprocess completed")

                if self._interrupted:
                    continue

                _log("Step 3: Sleeping 0.1s for disk flush")
                time.sleep(0.1)

                _log("Step 4: Calling Win32Audio.play()")
                Win32Audio.play(temp_file)
                _log("Step 5: Win32Audio.play() returned, entering poll loop")
                
                while Win32Audio.is_playing() and not self._interrupted:
                    time.sleep(0.1)

                _log("Step 6: Playback loop finished, cleaning up")
                Win32Audio.stop()

                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                    except:
                        pass

                if not self._interrupted:
                    self.speech_finished.emit()
                _log("Step 8: Audio task completed successfully")

            except Exception as e:
                _log(f"ERROR in run(): {e}")
                self.error_occurred.emit(str(e))

