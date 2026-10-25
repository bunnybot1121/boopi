import os
import re
import time
import queue
import asyncio
import edge_tts
import json
import threading
from PyQt6.QtCore import QThread, pyqtSignal
import sounddevice as sd
try:
    import soundfile as sf
except ImportError:
    sf = None
import wave
import numpy as np

# -------------------------------------------------------------
# Configuration & Logger
# -------------------------------------------------------------
class SimpleLogger:
    def info(self, msg):
        print(f"From Python: [Speaker] {msg}", flush=True)
        try:
            from logger import crash_log
            crash_log(f"[Speaker] INFO: {msg}")
        except Exception:
            pass
    def warning(self, msg):
        print(f"From Python: [Speaker Warning] {msg}", flush=True)
        try:
            from logger import crash_log
            crash_log(f"[Speaker] WARNING: {msg}")
        except Exception:
            pass
    def error(self, msg):
        print(f"From Python: [Speaker Error] {msg}", flush=True)
        try:
            from logger import crash_log
            crash_log(f"[Speaker] ERROR: {msg}")
        except Exception:
            pass

log = SimpleLogger()

import config
ELEVENLABS_API_KEY = getattr(config, "ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = getattr(config, "ELEVENLABS_VOICE_ID", "")
TTS_VOICE = getattr(config, "TTS_VOICE", "en-US-AnaNeural")
USE_CLOUD_TTS = getattr(config, "USE_CLOUD_TTS", True)

# -------------------------------------------------------------
# Helpers
# -------------------------------------------------------------
def split_into_sentences(text: str) -> list:
    """Splits a paragraph into individual sentences using standard punctuation
    and Devanagari danda characters, ignoring common abbreviations.
    """
    sentence_end = re.compile(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|\!|।)\s')
    sentences = sentence_end.split(text)
    return [s.strip() for s in sentences if s.strip()]

def strip_emojis(text: str) -> str:
    """Removes all emojis and Dingbats characters to prevent TTS engines from reading emoji names."""
    clean_chars = []
    for char in text:
        ord_val = ord(char)
        if (0x2600 <= ord_val <= 0x27BF) or \
           (0x1F300 <= ord_val <= 0x1F64F) or \
           (0x1F680 <= ord_val <= 0x1F6FF) or \
           (0x1F900 <= ord_val <= 0x1F9FF) or \
           (0x1FA00 <= ord_val <= 0x1FAFF):
            continue
        clean_chars.append(char)
    return "".join(clean_chars)

def make_fluent(text: str) -> str:
    """Strips intermediate punctuation like commas, semicolons, and colons, 
    and replaces exclamations with periods, to ensure smooth/fluid TTS speech."""
    clean = text.replace(",", "").replace(";", "").replace(":", "")
    clean = clean.replace("!", ".")
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()

def apply_mascot_pitch_shift(wav_path: str, semitones: float = 3.5):
    """Applies real-time pitch shifting to offline Piper speech to match Boopi's cute mascot pitch."""
    try:
        import soundfile as sf
        import torch
        import torchaudio
        data, sr = sf.read(wav_path)
        tensor = torch.from_numpy(data).float().unsqueeze(0)
        shifted = torchaudio.functional.pitch_shift(tensor, sr, n_steps=semitones)
        sf.write(wav_path, shifted.squeeze(0).numpy(), sr)
    except Exception:
        pass

# -------------------------------------------------------------
# 0-ms Audio Voice Cache
# -------------------------------------------------------------
import hashlib

VOICE_CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "voice_cache"))

def get_cached_voice_file(text: str):
    if not os.path.isdir(VOICE_CACHE_DIR):
        return None
    clean_text = make_fluent(strip_emojis(text)).lower()
    clean_key = re.sub(r'\s+', ' ', clean_text).strip()
    if not clean_key:
        return None
    h = hashlib.md5(clean_key.encode("utf-8")).hexdigest()
    mp3_path = os.path.join(VOICE_CACHE_DIR, f"{h}.mp3")
    if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 100:
        return mp3_path
    wav_path = os.path.join(VOICE_CACHE_DIR, f"{h}.wav")
    if os.path.exists(wav_path) and os.path.getsize(wav_path) > 100:
        return wav_path

    # Resilient semantic fallback for common boot/startup phrases
    if "getting warmed up and loading my systems" in clean_key:
        fallback = os.path.join(VOICE_CACHE_DIR, "23376d38edda2e18ba89514cefaf3a3d.mp3")
        if os.path.exists(fallback):
            return fallback
    if "all systems are online and ready" in clean_key:
        fallback = os.path.join(VOICE_CACHE_DIR, "520d63565fef50922a44e5a3d3bb2c80.mp3")
        if os.path.exists(fallback):
            return fallback

    return None

_global_speaker_is_playing = False

def is_speaker_playing() -> bool:
    global _global_speaker_is_playing
    return _global_speaker_is_playing

# -------------------------------------------------------------
# Speaker Thread
# -------------------------------------------------------------
class SpeakerThread(QThread):
    speech_started  = pyqtSignal()
    speech_finished = pyqtSignal()
    error_occurred  = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self._text_queue = queue.Queue()
        self._play_queue = queue.Queue()
        self._epoch = 0
        self._exit_flag = False
        self._lock = threading.Lock()
        self._output_lock = threading.Lock()
        self._output_stream = None
        self._chunk_counter = 0
        
        # Clean up any leftover temp audio files from previous sessions
        try:
            for f in os.listdir('.'):
                if f.startswith('temp_speech_') and (f.endswith('.mp3') or f.endswith('.wav')):
                    try: os.remove(f)
                    except: pass
        except Exception:
            pass

        self.piper_voice = None
        # Initialize Local Offline Piper Neural Voice eagerly in background
        threading.Thread(target=self._init_piper, daemon=True).start()

        # Start background synthesis loop
        self._synthesis_thread = threading.Thread(target=self._synthesis_loop, daemon=True)
        self._synthesis_thread.start()
        
        self.start()

    def _init_piper(self):
        try:
            import piper
            piper_dir = getattr(config, "PIPER_MODEL_DIR", None)
            if not piper_dir or not os.path.isdir(piper_dir):
                piper_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "models", "piper"))
            voice_name = getattr(config, "PIPER_VOICE", "en_US-amy-medium")
            model_path = os.path.join(piper_dir, f"{voice_name}.onnx")
            config_path = os.path.join(piper_dir, f"{voice_name}.onnx.json")
            
            if not os.path.exists(model_path) and os.path.isdir(piper_dir):
                for f in os.listdir(piper_dir):
                    if f.endswith(".onnx"):
                        model_path = os.path.join(piper_dir, f)
                        config_path = os.path.join(piper_dir, f + ".json")
                        break

            if os.path.exists(model_path) and os.path.exists(config_path):
                log.info(f"Loading local offline Piper Neural TTS model ({os.path.basename(model_path)})...")
                self.piper_voice = piper.PiperVoice.load(model_path, config_path=config_path)
                log.info("Local Piper Neural TTS model loaded successfully!")
            else:
                log.warning(f"Piper model files not found at {model_path}. Will use SAPI5 fallback.")
        except Exception as e:
            log.warning(f"Could not initialize Piper TTS: {e}. Will use SAPI5 fallback.")

    def speak(self, text: str):
        self.say(text)

    def say(self, text: str, interrupt=True):
        if not text or not text.strip():
            return
            
        # Strip markdown formatting
        text = text.replace("*", "").replace("_", "").replace("`", "")
            
        if not text.strip():
            return
            
        if interrupt:
            self.interrupt()
            
        # 0-ms whole-phrase pre-cached voice lookup (instant hardware playback)
        cached_file = get_cached_voice_file(text)
        if cached_file:
            log.info(f"0-ms Voice Cache HIT (phrase): '{text}' -> {os.path.basename(cached_file)}")
            with self._lock:
                self._play_queue.put((cached_file, text, self._epoch))
            return

        sentences = split_into_sentences(text)
        is_streaming = not interrupt
        with self._lock:
            for sentence in sentences:
                clean_text = make_fluent(strip_emojis(sentence))
                if not any(c.isalnum() for c in clean_text):
                    continue
                self._text_queue.put((sentence, self._epoch, is_streaming))

    def stop(self):
        self.interrupt(emit_finished=True)

    def is_playing(self) -> bool:
        global _global_speaker_is_playing
        return _global_speaker_is_playing

    def interrupt(self, emit_finished=False):
        global _global_speaker_is_playing
        with self._lock:
            self._epoch += 1
            
            # Clear text queue
            while not self._text_queue.empty():
                try:
                    self._text_queue.get_nowait()
                except queue.Empty:
                    break
            
            # Clear play queue and delete temp files (never delete static voice cache files!)
            while not self._play_queue.empty():
                try:
                    item = self._play_queue.get_nowait()
                    if item:
                        temp_path = item[0]
                        if not temp_path.startswith(VOICE_CACHE_DIR) and os.path.exists(temp_path):
                            os.remove(temp_path)
                except queue.Empty:
                    break
                except Exception as e:
                    log.warning(f"Error cleaning play queue during interrupt: {e}")
        
        # Instantly mark not playing. Incrementing self._epoch cleanly terminates
        # the playback loop in run() within <40ms on its own thread, avoiding PortAudio C-level Access Violations.
        with self._output_lock:
            _global_speaker_is_playing = False
        
        if emit_finished:
            try:
                self.speech_finished.emit()
            except Exception:
                pass

    def quit(self):
        self.interrupt()
        self._exit_flag = True
        self._text_queue.put(None)
        self._play_queue.put(None)
        self.wait(1000)

    def run(self):
        global _global_speaker_is_playing
        while not self._exit_flag:
            item = self._play_queue.get()
            if item is None:
                break
                
            temp_path, text, epoch = item
            with self._lock:
                if epoch != self._epoch or self._exit_flag:
                    if not temp_path.startswith(VOICE_CACHE_DIR) and os.path.exists(temp_path):
                        try: os.remove(temp_path)
                        except: pass
                    continue
                
            # Read audio data into memory via soundfile or wave
            try:
                if sf is not None:
                    data, fs = sf.read(temp_path, dtype='float32')
                else:
                    with wave.open(temp_path, 'rb') as wf:
                        fs = wf.getframerate()
                        frames = wf.readframes(wf.getnframes())
                        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            except Exception as e:
                log.error(f"Error reading audio file {temp_path}: {e}")
                if not temp_path.startswith(VOICE_CACHE_DIR) and os.path.exists(temp_path):
                    try: os.remove(temp_path)
                    except: pass
                continue

            # Data is loaded in RAM — remove temporary file immediately from disk!
            if not temp_path.startswith(VOICE_CACHE_DIR) and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception as e:
                    log.warning(f"Could not remove temp audio file {temp_path}: {e}")
                
            if temp_path.endswith(".wav"):
                companion_mp3 = temp_path[:-4] + ".mp3"
                if os.path.exists(companion_mp3):
                    try: os.remove(companion_mp3)
                    except: pass

            with self._lock:
                if epoch != self._epoch or self._exit_flag:
                    continue

            # Print IPC subtitles message for Electron
            print(json.dumps({"type": "speech_text", "value": text}), flush=True)
            print(f"From Python: [TTS] Playing audio ({len(data)/fs:.2f}s)...", flush=True)
            
            self.speech_started.emit()
            _global_speaker_is_playing = True

            try:
                channels = 1 if data.ndim == 1 else data.shape[1]
                stream = sd.OutputStream(
                    samplerate=fs,
                    channels=channels,
                    dtype='float32'
                )
                with self._output_lock:
                    if epoch != self._epoch or self._exit_flag:
                        stream.close(ignore_errors=True)
                        _global_speaker_is_playing = False
                        continue
                    self._output_stream = stream
                    stream.start()

                # Stream audio in small 1024-frame chunks (~42ms) with instant epoch interrupt check
                chunk_size = 1024
                num_frames = len(data)
                offset = 0
                while offset < num_frames and not self._exit_flag:
                    if epoch != self._epoch:
                        break
                    end_idx = min(offset + chunk_size, num_frames)
                    chunk = data[offset:end_idx]
                    try:
                        stream.write(chunk)
                    except Exception:
                        break
                    offset = end_idx

                with self._output_lock:
                    if self._output_stream == stream:
                        try:
                            stream.stop(ignore_errors=True)
                            stream.close(ignore_errors=True)
                        except Exception:
                            pass
                        self._output_stream = None
            except Exception as play_err:
                log.error(f"Playback error via sounddevice: {play_err}")
                self.error_occurred.emit(str(play_err))
                with self._output_lock:
                    self._output_stream = None
            finally:
                _global_speaker_is_playing = False
            
            # Check if this was the last item for this epoch
            with self._lock:
                if self._text_queue.empty() and self._play_queue.empty() and epoch == self._epoch:
                    self.speech_finished.emit()

    def _synthesis_loop(self):
        while not self._exit_flag:
            item = self._text_queue.get()
            if item is None:
                break
                
            if len(item) == 3:
                text, epoch, is_streaming = item
            else:
                text, epoch = item
                is_streaming = False

            with self._lock:
                if epoch != self._epoch or self._exit_flag:
                    continue

            # 0. Check 0-ms Pre-rendered Voice Cache (only for standalone commands/greetings, never mid-stream)
            if not is_streaming:
                cached_file = get_cached_voice_file(text)
                if cached_file:
                    log.info(f"0-ms Voice Cache HIT: '{text}' -> {os.path.basename(cached_file)}")
                    with self._lock:
                        if epoch == self._epoch and not self._exit_flag:
                            self._play_queue.put((cached_file, text, epoch))
                    continue
                
            self._chunk_counter += 1
            temp_path = os.path.abspath(f"temp_speech_{self._chunk_counter}.mp3")
            
            # 1. Synthesize TTS
            async def generate_tts(text_val, path_val):
                nonlocal temp_path
                tts_text = strip_emojis(text_val)
                fluent_text = make_fluent(tts_text)

                # 0. 100% Local Offline High-Quality Neural Speech via Piper TTS
                if not USE_CLOUD_TTS:
                    wav_path = path_val[:-4] + ".wav" if path_val.endswith(".mp3") else path_val
                    
                    # Try local Piper Neural TTS first (fast, natural studio-grade offline voice)
                    if self.piper_voice:
                        try:
                            import wave
                            with wave.open(wav_path, "wb") as wf:
                                self.piper_voice.synthesize_wav(fluent_text, wf)
                            if os.path.exists(wav_path) and os.path.getsize(wav_path) > 200:
                                temp_path = wav_path
                                log.info(f"Local Piper Neural speech generated (offline fallback): {os.path.basename(wav_path)}")
                                return
                        except Exception as piper_err:
                            log.warning(f"Piper synthesis error: {piper_err}. Falling back to SAPI.")

                    # Fallback to Windows SAPI5 if Piper not ready
                    try:
                        import win32com.client
                        speaker_obj = win32com.client.Dispatch("SAPI.SpVoice")
                        for v in speaker_obj.GetVoices():
                            desc = v.GetDescription().lower()
                            if "zira" in desc or "female" in desc or "eva" in desc or "hazel" in desc:
                                speaker_obj.Voice = v
                                break
                        stream = win32com.client.Dispatch("SAPI.SpFileStream")
                        stream.Open(wav_path, 3, False)
                        speaker_obj.AudioOutputStream = stream
                        speaker_obj.Speak(fluent_text)
                        stream.Close()
                        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 200:
                            temp_path = wav_path
                            log.info(f"Local SAPI speech generated (offline fallback): {os.path.basename(wav_path)}")
                            return
                    except Exception as sapi_err:
                        log.error(f"Local SAPI synthesis error: {sapi_err}")
                        raise sapi_err

                # 1. ElevenLabs Synthesis (Optional override if cloud enabled)
                if ELEVENLABS_API_KEY:
                    try:
                        voice_id = ELEVENLABS_VOICE_ID or "jUjRbhZWoMK4aDciW36V"
                        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                        headers = {
                            "Accept": "audio/mpeg",
                            "Content-Type": "application/json",
                            "xi-api-key": ELEVENLABS_API_KEY
                        }
                        
                        tts_text = strip_emojis(text_val)
                        fluent_text = make_fluent(tts_text)
                        
                        payload = {
                            "text": fluent_text,
                            "model_id": "eleven_multilingual_v2",
                            "voice_settings": {
                                "stability": 0.65,
                                "similarity_boost": 0.85
                            }
                        }
                        
                        try:
                            import requests
                            response = requests.post(url, json=payload, headers=headers, timeout=10)
                            if response.status_code == 200:
                                with open(path_val, "wb") as f:
                                    f.write(response.content)
                                return
                            else:
                                log.error(f"ElevenLabs TTS response error (code {response.status_code}): {response.text}")
                        except ImportError:
                            import urllib.request
                            import json
                            req = urllib.request.Request(
                                url,
                                data=json.dumps(payload).encode("utf-8"),
                                headers=headers,
                                method="POST"
                            )
                            with urllib.request.urlopen(req, timeout=10) as resp:
                                if resp.status == 200:
                                    with open(path_val, "wb") as f:
                                        f.write(resp.read())
                                    return
                    except Exception as ex:
                        log.error(f"ElevenLabs synthesis failed: {ex}. Falling back to edge-tts.")

                # 2. Resilient Edge-TTS Synthesis with Multi-Attempt Retry Loop
                # Strictly lock voice identity and acoustic parameters across all sentences
                voice = TTS_VOICE or 'en-US-AnaNeural'
                rate = "+0%"
                pitch = "+0Hz"
                
                tts_text = strip_emojis(text_val)
                fluent_text = make_fluent(tts_text)
                
                max_retries = 2
                edge_success = False
                last_edge_err = None
                
                for attempt in range(1, max_retries + 1):
                    try:
                        # Clean up any partial/stale file before each attempt
                        if os.path.exists(path_val):
                            try: os.remove(path_val)
                            except: pass
                            
                        communicate = edge_tts.Communicate(fluent_text, voice, rate=rate, pitch=pitch)
                        await asyncio.wait_for(communicate.save(path_val), timeout=6.0)
                        
                        if os.path.exists(path_val) and os.path.getsize(path_val) > 500:
                            edge_success = True
                            break
                        else:
                            if os.path.exists(path_val):
                                try: os.remove(path_val)
                                except: pass
                            raise RuntimeError(f"Edge-TTS produced invalid/empty audio file")
                    except Exception as edge_err:
                        last_edge_err = edge_err
                        if os.path.exists(path_val):
                            try: os.remove(path_val)
                            except: pass
                        if attempt < max_retries:
                            log.warning(f"Edge-TTS attempt {attempt}/{max_retries} failed ({edge_err}). Retrying in {0.25 * attempt}s...")
                            await asyncio.sleep(0.25 * attempt)
                
                if edge_success:
                    return

                # 3. Emergency Offline Neural Piper / SAPI fallback
                log.warning(f"Edge-TTS unavailable after {max_retries} attempts ({last_edge_err}). Falling back to offline speech...")
                wav_path = path_val[:-4] + ".wav" if path_val.endswith(".mp3") else path_val
                if self.piper_voice:
                    try:
                        import wave
                        with wave.open(wav_path, "wb") as wf:
                            self.piper_voice.synthesize_wav(fluent_text, wf)
                        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 200:
                            temp_path = wav_path
                            log.info(f"Offline Piper Neural speech generated: {os.path.basename(wav_path)}")
                            return
                    except Exception as p_err:
                        log.warning(f"Offline Piper fallback failed: {p_err}")
                try:
                    import win32com.client
                    speaker_obj = win32com.client.Dispatch("SAPI.SpVoice")
                    try:
                        for v in speaker_obj.GetVoices():
                            desc = v.GetDescription().lower()
                            if "zira" in desc or "female" in desc or "eva" in desc or "hazel" in desc:
                                speaker_obj.Voice = v
                                break
                    except Exception as v_err:
                        log.warning(f"Could not set female SAPI voice: {v_err}")
                    stream = win32com.client.Dispatch("SAPI.SpFileStream")
                    stream.Open(wav_path, 3, False)
                    speaker_obj.AudioOutputStream = stream
                    speaker_obj.Speak(fluent_text)
                    stream.Close()
                    if os.path.exists(wav_path) and os.path.getsize(wav_path) > 200:
                        temp_path = wav_path
                except Exception as sapi_err:
                    log.error(f"Offline SAPI fallback failed: {sapi_err}")
                    raise sapi_err

            try:
                # Run async save in background thread sync loop
                asyncio.run(generate_tts(text, temp_path))
            except Exception as e:
                log.error(f"TTS Synthesis failure: {e}")
                self.error_occurred.emit(f"TTS Gen Error: {e}")
                if os.path.exists(temp_path):
                    try: os.remove(temp_path)
                    except: pass
                continue
                
            with self._lock:
                if epoch != self._epoch or self._exit_flag:
                    if os.path.exists(temp_path):
                        try: os.remove(temp_path)
                        except: pass
                    continue
                
            # Enqueue the synthesized file for playback
            self._play_queue.put((temp_path, text, epoch))
