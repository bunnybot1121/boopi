import os
import ctypes
import time
from PyQt6.QtCore import QThread, pyqtSignal
import asyncio
import edge_tts

class Win32Audio:
    @staticmethod
    def play(path):
        Win32Audio.stop()
        abs_path = os.path.abspath(path)
        print(f"From Python: [TTS] Playing audio from {abs_path}...", flush=True)
        res1 = ctypes.windll.winmm.mciSendStringW(f'open "{abs_path}" alias mp3audio', None, 0, None)
        res2 = ctypes.windll.winmm.mciSendStringW(f'play mp3audio', None, 0, None)
        if res1 != 0 or res2 != 0:
            print(f"From Python: [TTS] Audio player error codes: {res1}, {res2}", flush=True)
        
    @staticmethod
    def is_playing():
        status = ctypes.create_unicode_buffer(255)
        ctypes.windll.winmm.mciSendStringW(f'status mp3audio mode', status, 255, None)
        return status.value == "playing"
        
    @staticmethod
    def stop():
        ctypes.windll.winmm.mciSendStringW(f'stop mp3audio', None, 0, None)
        ctypes.windll.winmm.mciSendStringW(f'close mp3audio', None, 0, None)

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
        Win32Audio.stop()

    def run(self):
        try:
            if self._interrupted:
                return

            self.speech_started.emit()
            
            # Using AnaNeural which is specifically tuned for 'Cute, Cartoon' anime-style voices
            temp_file = "temp_speech.mp3"
            voice = "en-US-AnaNeural"
            
            # Generate audio synchronously using asyncio loop
            communicate = edge_tts.Communicate(self._text, voice)
            asyncio.run(communicate.save(temp_file))

            if self._interrupted:
                return

            # Play audio
            Win32Audio.play(temp_file)
            
            # Wait for playback to finish
            while Win32Audio.is_playing() and not self._interrupted:
                time.sleep(0.1)

            # Cleanup
            Win32Audio.stop()
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

            if not self._interrupted:
                self.speech_finished.emit()

        except Exception as e:
            self.error_occurred.emit(str(e))
