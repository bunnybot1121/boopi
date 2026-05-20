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
        self._text_queue = queue.Queue()
        self._audio_queue = queue.Queue()
        self._epoch = 0
        self._chunk_counter = 0
        self._exit_flag = False
        self.start()

    def say(self, text: str, interrupt=True):
        if not text or not text.strip():
            return
            
        try:
            import emoji
            text = emoji.replace_emoji(text, replace="")
            text = text.replace("*", "") # Strip markdown asterisks
        except ImportError:
            pass
            
        if not text.strip():
            return
        
        if interrupt:
            self.interrupt()
            
        self._text_queue.put((text, self._epoch))

    def interrupt(self):
        self._epoch += 1
        Win32Audio.stop()
        while not self._text_queue.empty():
            try:
                self._text_queue.get_nowait()
            except queue.Empty:
                break
        while not self._audio_queue.empty():
            try:
                path, _ = self._audio_queue.get_nowait()
                if path and os.path.exists(path):
                    try: os.remove(path)
                    except: pass
            except queue.Empty:
                break

    def quit(self):
        self.interrupt()
        self._exit_flag = True
        self._text_queue.put(None)
        self._audio_queue.put(None)

    def run(self):
        from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
        from PyQt6.QtCore import QUrl, QEventLoop, QTimer

        def tts_generator_loop():
            import asyncio
            import edge_tts
            voice = "en-US-AnaNeural"
            
            async def generate_tts(text_val, path_val):
                communicate = edge_tts.Communicate(text_val, voice)
                await communicate.save(path_val)

            while True:
                item = self._text_queue.get()
                if item is None:
                    break
                
                text, epoch = item
                if epoch != self._epoch or self._exit_flag:
                    continue
                
                self._chunk_counter += 1
                out_path = f"temp_speech_{self._chunk_counter}.mp3"
                try:
                    # Native async generation inside python (extremely fast)
                    asyncio.run(generate_tts(text, out_path))
                    
                    if epoch == self._epoch and not self._exit_flag:
                        self._audio_queue.put((out_path, epoch))
                    else:
                        if os.path.exists(out_path):
                            try: os.remove(out_path)
                            except: pass
                except Exception as e:
                    _log(f"TTS Gen Error: {e}")

        gen_thread = threading.Thread(target=tts_generator_loop, daemon=True)
        gen_thread.start()

        while True:
            try:
                item = self._audio_queue.get()
                if item is None:
                    break
                
                path, epoch = item
                if epoch != self._epoch or self._exit_flag:
                    if os.path.exists(path):
                        try: os.remove(path)
                        except: pass
                    continue
                
                self.speech_started.emit()
                
                print(f"From Python: [TTS] Playing audio from {os.path.abspath(path)}...", flush=True)
                
                loop = QEventLoop()
                player = QMediaPlayer()
                audio = QAudioOutput()
                player.setAudioOutput(audio)
                player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
                
                def on_status(status):
                    if status == QMediaPlayer.MediaStatus.EndOfMedia or status == QMediaPlayer.MediaStatus.InvalidMedia:
                        loop.quit()
                player.mediaStatusChanged.connect(on_status)

                def check_interrupt():
                    if epoch != self._epoch or self._exit_flag:
                        player.stop()
                        loop.quit()

                timer = QTimer()
                timer.timeout.connect(check_interrupt)
                timer.start(100)
                
                player.play()
                loop.exec()
                
                timer.stop()
                timer.deleteLater()
                player.deleteLater()
                audio.deleteLater()
                
                if os.path.exists(path):
                    try: os.remove(path)
                    except: pass
                    
                if epoch == self._epoch and not self._exit_flag and self._text_queue.empty() and self._audio_queue.empty():
                    self.speech_finished.emit()

            except Exception as e:
                self.error_occurred.emit(str(e))

