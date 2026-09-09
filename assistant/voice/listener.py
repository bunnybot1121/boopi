from PyQt6.QtCore import QThread, pyqtSignal
import sounddevice as sd
import numpy as np
import collections
import warnings
import os
import sys
import time
import queue
import io
import wave
import threading
import string

warnings.filterwarnings("ignore", message=".*FP16 is not supported on CPU.*")

from state_manager import state_mgr

# -------------------------------------------------------------
# Configuration & Helpers
# -------------------------------------------------------------
SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000) # 480 samples
VAD_AGGRESSIVENESS = 2 # Balanced mode (filters hum while reliably catching voice)
MIN_SPEECH_FRAMES = 10
PRE_ROLL_FRAMES = 20

# Settings from environment variables with safe fallbacks (matching Hackathon project)
USE_CLOUD_STT = os.environ.get("USE_CLOUD_STT", "true").lower() == "true"
LOCAL_WHISPER_MODEL = os.environ.get("LOCAL_WHISPER_MODEL", "base")
GROQ_STT_MODEL = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3")
AUDIO_GAIN_BOOST = float(os.environ.get("AUDIO_GAIN_BOOST", "1.5"))
SILENCE_FRAMES = int(os.environ.get("SILENCE_FRAMES", "13")) # Wait 390ms (13 frames) of continuous silence for fast snappy response

PROMPT_CONTEXT = (
    "Prag, prag, PRAG, bot, robot, move the bot 10 cm, move 12 cm, move 20 cm, scan the room, scan, "
    "Boopi, Bupi, Boopy, Boopie, find the human in the room, find human, locate person, search room, "
    "turn 90 degrees, turn left, turn right, spin, rotate 180 degrees, turn around, walk until obstacle, approach person, "
    "patrol area, patrol and inspect, explore, start obstacle avoidance, stop obstacle avoidance, auto avoid, roam around, "
    "move forward, move backward, drive reverse, turn left, turn right, stop, halt, freeze, emergency stop, e-stop, "
    "what did you find, mission report, debrief, relay on, relay off, gas reading, mq2 gas sensor, check gas sensor, "
    "ultrasonic distance, front distance, check distance, check temperature, status, world state, esp32 connected, active nodes."
)

class SimpleLogger:
    def info(self, msg):
        print(f"From Python: [Listener] {msg}", flush=True)
        try:
            from logger import crash_log
            crash_log(f"[Listener] INFO: {msg}")
        except Exception:
            pass
    def warning(self, msg):
        print(f"From Python: [Listener Warning] {msg}", flush=True)
        try:
            from logger import crash_log
            crash_log(f"[Listener] WARNING: {msg}")
        except Exception:
            pass
    def error(self, msg):
        print(f"From Python: [Listener Error] {msg}", flush=True)
        try:
            from logger import crash_log
            crash_log(f"[Listener] ERROR: {msg}")
        except Exception:
            pass

log = SimpleLogger()

def strip_punctuation(word: str) -> str:
    return "".join(c for c in word if c not in string.punctuation)

def is_hallucinated_output(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return False
    
    stripped = normalized.rstrip(".,?!;:-")
    
    always_hallucination = [
        "[blank_audio]", "[ blank_audio ]", "[blank audio]", "(blank audio)",
        "thank you for watching", "thanks for watching", "thank you for listening",
        "thanks for listening", "thank you so much", "please subscribe",
        "like and subscribe", "see you next time", "see you in the next video",
        "bye bye", "...", ".", ",", "!", "?", "thank you", "thank you.",
        "thanks.", "bye.", "goodbye.", "goodbye"
    ]
    
    if normalized in always_hallucination or stripped in always_hallucination:
        return True
        
    raw_words = normalized.split()
    if len(raw_words) < 3:
        return False
        
    clean_words = [strip_punctuation(w) for w in raw_words if strip_punctuation(w)]
    if not clean_words:
        return False
        
    first = clean_words[0]
    if all(w == first for w in clean_words):
        return True
        
    for n in range(1, 4):
        if len(clean_words) >= n * 2 and len(clean_words) % n == 0:
            pattern = clean_words[:n]
            all_match = True
            for i in range(0, len(clean_words), n):
                if clean_words[i:i+n] != pattern:
                    all_match = False
            if all_match:
                return True
                
    counts = collections.Counter(clean_words)
    total = len(clean_words)
    for word, count in counts.items():
        if count >= 5 and (count / total) > 0.6:
            return True
            
    return False

def get_groq_keys():
    keys = []
    if os.environ.get("GROQ_API_KEY"):
        keys.append(os.environ.get("GROQ_API_KEY"))
    for i in range(2, 11):
        key = os.environ.get(f"GROQ_API_KEY_{i}")
        if key:
            keys.append(key)
    return keys

def get_google_keys():
    keys = []
    # Primary key
    if os.environ.get("GOOGLE_AI_STUDIO_KEY"):
        keys.append(os.environ.get("GOOGLE_AI_STUDIO_KEY"))
    # Fallback keys
    for k, v in os.environ.items():
        if k.startswith("GOOGLE_AI_STUDIO_KEY_") and v.strip():
            keys.append(v.strip())
        elif k == "GEMINI_API_KEY" and v.strip():
            keys.append(v.strip())
    # Remove duplicates preserving order
    seen = set()
    return [k for k in keys if not (k in seen or seen.add(k))]

# -------------------------------------------------------------
# Listener Thread
# -------------------------------------------------------------
class ListenerThread(QThread):
    transcription_ready = pyqtSignal(str)
    listening_started   = pyqtSignal()
    listening_stopped   = pyqtSignal()
    error_occurred      = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._running = False
        self._paused = False
        self.whisper_model = None
        self.is_speaking = False
        self._energy_threshold = 30.0
        self.audio_queue = queue.Queue()
        
        # Initialize Local Faster-Whisper model in background eagerly
        threading.Thread(target=self._init_whisper, daemon=True).start()

    def _init_whisper(self):
        try:
            # Register NVIDIA CUDA 12 DLLs for Windows CTranslate2
            if sys.platform == "win32":
                nvidia_dirs = [
                    os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "cublas", "bin"),
                    os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "cudnn", "bin"),
                    os.path.join(sys.prefix, "Lib", "site-packages", "nvidia", "cuda_nvrtc", "bin"),
                ]
                for p in nvidia_dirs:
                    if os.path.exists(p):
                        try:
                            os.add_dll_directory(p)
                        except Exception:
                            pass
                        if p not in os.environ.get("PATH", ""):
                            os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")

            from faster_whisper import WhisperModel
            cuda_avail = False
            try:
                import ctranslate2
                cuda_avail = (ctranslate2.get_cuda_device_count() > 0)
            except Exception:
                pass
            if not cuda_avail:
                try:
                    import torch
                    cuda_avail = torch.cuda.is_available()
                except Exception:
                    pass
                
            device = "cuda" if cuda_avail else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"
            log.info(f"Initializing local Faster-Whisper model ({LOCAL_WHISPER_MODEL}) on {device} ({compute_type})...")
            # Disable symlink warnings on Windows to avoid clutter
            os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
            # Restrict CPU threads to avoid OpenMP deadlocks on Windows CPU execution
            self.whisper_model = WhisperModel(
                LOCAL_WHISPER_MODEL, 
                device=device, 
                compute_type=compute_type,
                cpu_threads=4
            )
            log.info(f"Local Faster-Whisper model ({LOCAL_WHISPER_MODEL}) loaded successfully on {device}!")
        except Exception as e:
            log.warning(f"Could not load local faster-whisper ({e}). Will use cloud STT fallback.")

    def stop(self):
        self._running = False
        self.wait()

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def run(self):
        log.info("ListenerThread: run() started.")
        self._running = True
        
        # Ensure Windows microphone is unmuted and volume is healthy
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            import ctypes
            mic_dev = AudioUtilities.GetMicrophone()
            if mic_dev:
                interface = mic_dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                vol = ctypes.cast(interface, ctypes.POINTER(IAudioEndpointVolume))
                if vol.GetMute():
                    vol.SetMute(0, None)
                    log.info("Windows microphone was MUTED. Automatically unmuted it!")
                if vol.GetMasterVolumeLevelScalar() < 0.7:
                    vol.SetMasterVolumeLevelScalar(1.0, None)
                    log.info("Microphone volume was low. Automatically raised to 100%!")
        except Exception as e:
            log.warning(f"Could not check/unmute Windows mic via pycaw: {e}")
        
        def callback(indata, frames, time_info, status):
            if status:
                log.warning(f"Audio input status warning: {status}")
            self.audio_queue.put(indata.copy())

        try:
            stream = None
            # Attempt opening default sound input device
            try:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=1,
                    dtype='int16',
                    blocksize=FRAME_SAMPLES,
                    callback=callback
                )
            except Exception as e:
                log.warning(f"Default input device failed: {e}. Attempting fallback channels...")
                for i, dev in enumerate(sd.query_devices()):
                    if dev['max_input_channels'] > 0:
                        try:
                            stream = sd.InputStream(
                                device=i,
                                samplerate=SAMPLE_RATE,
                                channels=1,
                                dtype='int16',
                                blocksize=FRAME_SAMPLES,
                                callback=callback
                            )
                            log.info(f"Selected fallback input device {i}: {dev['name']}")
                            break
                        except Exception:
                            stream = None
                            continue
                  
            if stream is None:
                raise Exception("Could not open any audio input device.")

            with stream:
                import webrtcvad
                vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
                log.info("WebRTC VAD Initialized. Active noise cancellation active.")

                # Microphone Calibration (1 second)
                ambient_frames = []
                log.info("Calibrating microphone ambient energy levels for 1 second...")
                
                # Clear any stale frames from queue first
                while not self.audio_queue.empty():
                    try:
                        self.audio_queue.get_nowait()
                    except queue.Empty:
                        break

                start_cal = time.time()
                while time.time() - start_cal < 1.0:
                    try:
                        data = self.audio_queue.get(timeout=0.05)
                        rms = np.sqrt(np.mean(np.square(data, dtype=np.float32)))
                        ambient_frames.append(rms)
                    except queue.Empty:
                        continue
                  
                if ambient_frames:
                    avg_ambient = sum(ambient_frames) / len(ambient_frames)
                    lower_clamp = 1.0 if avg_ambient < 5.0 else 6.0
                    self._energy_threshold = np.clip(avg_ambient * AUDIO_GAIN_BOOST, lower_clamp, 25.0)
                else:
                    avg_ambient = 0.0
                    self._energy_threshold = 6.0
                log.info(f"Calibration complete. Ambient baseline: {avg_ambient:.2f}, Threshold: {self._energy_threshold:.2f}")

                ring_buffer = collections.deque(maxlen=PRE_ROLL_FRAMES)
                last_talking_time = 0
                
                while self._running:
                    triggered = False
                    voiced_frames = []
                    silence_count = 0
                    ring_buffer.clear()
                    speech_detected = False

                    # Main loop for frame capture
                    while self._running:
                        # If paused or Bupi is actively speaking, ignore audio input to prevent feedback loops
                        if self._paused or getattr(self, "is_speaking", False):
                            last_talking_time = time.time()
                            ring_buffer.clear()
                            triggered = False
                            voiced_frames.clear()
                            while not self.audio_queue.empty():
                                try:
                                    self.audio_queue.get_nowait()
                                except queue.Empty:
                                    break
                            time.sleep(0.05)
                            continue
                          
                        # Short 0.25s cooldown after Bupi stops talking to avoid picking up speaker echo
                        if not getattr(self, "is_speaking", False) and time.time() - last_talking_time < 0.25:
                            ring_buffer.clear()
                            triggered = False
                            voiced_frames.clear()
                            while not self.audio_queue.empty():
                                try:
                                    self.audio_queue.get_nowait()
                                except queue.Empty:
                                    break
                            time.sleep(0.05)
                            continue

                        try:
                            data = self.audio_queue.get(timeout=0.05)
                        except queue.Empty:
                            continue

                        # Standard WebRTC VAD pre-filtering & trigger
                        if len(data) > 0:
                            rms = float(np.sqrt(np.mean(np.square(data, dtype=np.float32))))
                        else:
                            rms = 0.0
                          
                        is_speech = False

                        # Energy pre-filtering (threshold is boosted while speaking to reduce self-trigger)
                        current_threshold = self._energy_threshold
                        if getattr(self, "is_speaking", False):
                            current_threshold *= 2.8

                        # SNR-aware candidate gating (dynamically adapts to ambient room noise)
                        snr_gate = max(avg_ambient * 2.2, 12.0)
                        if rms > current_threshold:
                            max_val = float(np.percentile(np.abs(data), 98)) if len(data) > 0 else 0.0
                            # Only treat as speech candidate if above adaptive background noise floor
                            if max_val >= snr_gate:
                                gain = min(22000.0 / max(max_val, 1.0), 15.0)
                                amplified = np.clip(data.astype(np.float32) * gain, -32768, 32767).astype(np.int16)
                                frame = amplified.flatten().tobytes()
                                try:
                                    is_speech = vad.is_speech(frame, SAMPLE_RATE)
                                except Exception:
                                    is_speech = False
                            else:
                                is_speech = False
                        else:
                            is_speech = False

                        # Continuous ambient noise tracking when idle (dynamically adapts to AC, fan, or room noise)
                        if not is_speech and not triggered and not getattr(self, "is_speaking", False):
                            avg_ambient = 0.96 * avg_ambient + 0.04 * rms
                            self._energy_threshold = np.clip(avg_ambient * AUDIO_GAIN_BOOST + 1.0, 1.5, 35.0)

                        if not triggered:
                            # Standard VAD trigger when VAD thresholds met
                            ring_buffer.append((data.flatten().tobytes(), is_speech))
                            num_voiced = sum(1 for _, s in ring_buffer if s)
                            if num_voiced >= 0.25 * ring_buffer.maxlen: # 5 out of 20 frames = ~150ms of natural speech
                                triggered = True
                                voiced_frames.extend([f for f, _ in ring_buffer])
                                ring_buffer.clear()
                                log.info("VAD Speech started...")
                                
                                # Emit listening started signal (main.py will handle barge-in stopping the speaker)
                                self.listening_started.emit()
                        else:
                            # Once triggered, record voiced frames
                            voiced_frames.append(data.flatten().tobytes())
                            # Energy-verified speech hangover: only reset silence counter if actual voice energy
                            if is_speech and rms > current_threshold * 1.1:
                                silence_count = 0
                            else:
                                silence_count += 1
                                if silence_count > SILENCE_FRAMES:
                                    speech_detected = True
                                    break
                              
                            # Max recording length limit of 15 seconds
                            if len(voiced_frames) > int(15000 / FRAME_MS):
                                speech_detected = True
                                break

                    # Break thread if no longer running
                    if not self._running:
                        break

                    # Process transcription if VAD triggered speech window
                    if speech_detected:
                        log.info("Speech finished, processing transcription...")
                        
                        if len(voiced_frames) >= MIN_SPEECH_FRAMES:
                            audio = np.frombuffer(b''.join(voiced_frames), dtype=np.int16)
                            orig_max = float(np.percentile(np.abs(audio), 98)) if len(audio) > 0 else 0.0
                            
                            # Only transition to thinking if audio has confirmed vocal energy
                            if orig_max >= 15:
                                self.listening_stopped.emit()
                                
                                transcribe_thread = threading.Thread(
                                    target=self._transcribe_and_emit,
                                    args=(audio,),
                                    daemon=True
                                )
                                transcribe_thread.start()
                                
                                def watchdog():
                                    transcribe_thread.join(timeout=8.0)
                                    if transcribe_thread.is_alive():
                                        log.warning("Transcription timed out after 8 seconds. Resetting listener state.")
                                        self.transcription_ready.emit("")
                                
                                threading.Thread(target=watchdog, daemon=True).start()
                            else:
                                log.info(f"Discarded low-energy audio without thinking (peak: {orig_max:.1f} < 15)")
                                self.transcription_ready.emit("")
                        else:
                            self.transcription_ready.emit("")

        except Exception as e:
            log.error(f"Listener execution loop failed: {e}")
            self.error_occurred.emit(str(e))

    def _transcribe_and_emit(self, audio: np.ndarray):
        # Verify peak value before boosting to discard absolute silence
        orig_max = float(np.percentile(np.abs(audio), 98)) if len(audio) > 0 else 0.0
        if orig_max < 15:
            log.info(f"Discarded silent audio (peak: {orig_max} < 15)")
            self.transcription_ready.emit("")
            return

        # Soft peak normalization for quiet microphones
        if 0 < orig_max < 22000:
            gain = min(22000.0 / orig_max, 25.0)
            log.info(f"Soft peak normalization: peak={orig_max:.1f}, gain boost={gain:.2f}x")
            audio_boosted = audio.astype(np.float32) * gain
            np.clip(audio_boosted, -32768.0, 32767.0, out=audio_boosted)
            audio_gain = audio_boosted.astype(np.int16)
        else:
            audio_gain = audio

        # Normalize float32 1D array for Faster-Whisper
        audio_norm = audio_gain.flatten().astype(np.float32) / 32768.0
        text = ""
        
        # Generate WAV bytes in memory for cloud STT if enabled
        wav_bytes = None
        if USE_CLOUD_STT:
            try:
                wav_io = io.BytesIO()
                with wave.open(wav_io, 'wb') as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2) # 16-bit
                    wav_file.setframerate(SAMPLE_RATE)
                    wav_file.writeframes(audio_gain.tobytes())
                wav_bytes = wav_io.getvalue()
            except Exception as e:
                log.error(f"Failed to generate WAV bytes in memory: {e}")

        # 1. Primary: Cloud STT (Groq whisper-large-v3) - fastest and most accurate for all accents
        if USE_CLOUD_STT and wav_bytes:
            groq_keys = get_groq_keys()
            if groq_keys:
                text = self._groq_stt(wav_bytes, groq_keys)
            if not text:
                google_keys = get_google_keys()
                if google_keys:
                    text = self._gemini_stt(wav_bytes, google_keys)

        # 2. Offline Fallback: Local Faster-Whisper (base model, 100% offline, GPU/CPU)
        if not text:
            if not self.whisper_model:
                try:
                    self._init_whisper()
                except Exception as ex:
                    log.error(f"Could not initialize local Whisper: {ex}")
                    
            if self.whisper_model:
                try:
                    # Enforce language="en" so multilingual base model transcribes directly in English
                    segments, info = self.whisper_model.transcribe(
                        audio_norm, 
                        language="en", 
                        initial_prompt=PROMPT_CONTEXT, 
                        condition_on_previous_text=False,
                        beam_size=1,
                        best_of=1,
                        temperature=0.0,
                        vad_filter=True
                    )
                    text = " ".join([segment.text for segment in segments]).strip()
                    log.info(f"Local Faster-Whisper Transcription: '{text}'")
                except Exception as e:
                    log.warning(f"Local Faster-Whisper transcription error: {e}")
                    text = ""

        if text:
            # Hallucination Filtering from Voice Bundle
            clean_text = text.replace(",", "").replace(".", "").strip().lower()
            clean_prompt = PROMPT_CONTEXT.replace(",", "").replace(".", "").strip().lower()
            
            hallucinations = ["thank you", "thanks for watching", "please subscribe", "thank you.", "screencast", "goodbye"]
            
            prompt_words = [w for w in clean_prompt.split() if len(w) > 3]
            matched_words = sum(1 for w in prompt_words if w in clean_text)
            prompt_density = (matched_words / len(prompt_words)) if prompt_words else 0
            
            is_exact_prompt = (clean_text == clean_prompt) or (prompt_density > 0.6 and len(clean_text) > 40)
            is_hallucination = any(h in clean_text for h in hallucinations) or is_exact_prompt or is_hallucinated_output(text)
            
            if is_hallucination or (len(clean_text) <= 2 and clean_text not in ["hi", "go", "ok", "no"]):
                log.info(f"Filtered silence/hallucination (prompt density: {prompt_density:.2f}, robust check: {is_hallucinated_output(text)})")
                text = ""

        self.transcription_ready.emit(text)

    def _groq_stt(self, wav_bytes, keys):
        log.info("Running cloud transcription via Groq Whisper API...")
        import requests
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        
        for idx, key in enumerate(keys):
            try:
                log.info(f"Trying Groq STT key {idx+1}/{len(keys)}...")
                headers = {
                    "Authorization": f"Bearer {key}"
                }
                files = {
                    "file": ("speech.wav", wav_bytes, "audio/wav")
                }
                data = {
                    "model": GROQ_STT_MODEL,
                    "prompt": PROMPT_CONTEXT,
                    "response_format": "json"
                }
                
                response = requests.post(url, headers=headers, files=files, data=data, timeout=4.0)
                if response.status_code == 200:
                    result = response.json()
                    transcription = result.get("text", "").strip()
                    log.info(f"Groq API Transcription Success: '{transcription}'")
                    return transcription
                else:
                    log.warning(f"Groq STT key {idx+1} failed with status {response.status_code}: {response.text}")
            except requests.exceptions.ConnectionError:
                log.warning("No internet connection for Groq STT. Falling back immediately to local Whisper.")
                break
            except Exception as e:
                log.warning(f"Groq API transcription failed with key {idx+1}: {e}")
              
        return ""

    def _gemini_stt(self, wav_bytes, keys):
        log.info("Running cloud transcription via Gemini 2.5 Flash API...")
        from google import genai
        from google.genai import types
        
        for idx, key in enumerate(keys):
            try:
                log.info(f"Trying Gemini STT key {idx+1}/{len(keys)}...")
                client = genai.Client(api_key=key)
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        types.Part.from_bytes(
                            data=wav_bytes,
                            mime_type="audio/wav"
                        ),
                        f"Transcribe this audio file accurately. Output ONLY the transcription, with no extra text or commentary. Bias towards names/commands/vocabulary: {PROMPT_CONTEXT}"
                    ]
                )
                transcription = response.text.strip()
                log.info(f"Gemini API Transcription Success: '{transcription}'")
                return transcription
            except Exception as e:
                log.warning(f"Gemini STT failed with key {idx+1}: {e}")
              
        return ""
