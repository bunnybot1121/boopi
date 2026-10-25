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
import json

warnings.filterwarnings("ignore", message=".*FP16 is not supported on CPU.*")

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
import config

from state_manager import state_mgr
from logger import import_lock

# -------------------------------------------------------------
# Configuration & Helpers
# -------------------------------------------------------------
SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000) # 480 samples
VAD_AGGRESSIVENESS = int(os.environ.get("VAD_AGGRESSIVENESS", getattr(config, "VAD_AGGRESSIVENESS", 3)))
MIN_SPEECH_FRAMES = 12 # ~360ms minimum speech window to filter out brief clicks/speaker echo
PRE_ROLL_FRAMES = 20

# Settings from config / environment variables with safe fallbacks
USE_CLOUD_STT = getattr(config, "USE_CLOUD_STT", True)
LOCAL_WHISPER_MODEL = getattr(config, "LOCAL_WHISPER_MODEL", "base.en")
GROQ_STT_MODEL = getattr(config, "GROQ_STT_MODEL", "whisper-large-v3-turbo")
AUDIO_GAIN_BOOST = float(os.environ.get("AUDIO_GAIN_BOOST", getattr(config, "AUDIO_GAIN_BOOST", 1.5)))
SILENCE_FRAMES = int(os.environ.get("SILENCE_FRAMES", getattr(config, "SILENCE_FRAMES", 18))) # 540ms natural conversational pause

PROMPT_CONTEXT = "Hey Boopi, how are you? Hello Bupi, what's up? Boopi, Bupi, move forward, stop."

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
        "thanks.", "thanks", "bye.", "bye", "goodbye.", "goodbye", "you",
        "boopi, bupi.", "boopi, bupi", "boopi bupi", "boopi bupi bupi",
        "bupi bupi", "boopi boopi", "bupi boopi", "hvað er hann", "hvað er hann?",
        "hva er hann", "hva er hann?"
    ]
    
    if normalized in always_hallucination or stripped in always_hallucination:
        return True
        
    import re
    # Split on whitespace and punctuation symbols to detect tokens in hyphens/periods (e.g. "1-1-1-1-1" or "1. 1. 1.")
    raw_words = re.split(r"[\s\-_,.:;]+", normalized)
    clean_words = [strip_punctuation(w) for w in raw_words if strip_punctuation(w)]
    if len(clean_words) < 3:
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
    model_ready         = pyqtSignal(str)
    calibration_started = pyqtSignal()
    calibration_finished = pyqtSignal(float, float)

    def __init__(self):
        super().__init__()
        self._running = False
        self._paused = False
        self.whisper_model = None
        self.is_speaking = False
        self._energy_threshold = 30.0
        self.audio_queue = queue.Queue()
        
        # Local Faster-Whisper is loaded lazily on-demand if cloud STT is unavailable
        self.whisper_model = None

    def _init_whisper(self):
        if self.whisper_model is not None:
            return
        try:
            with import_lock:
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
            target_model = LOCAL_WHISPER_MODEL or "medium.en"
            log.info(f"Initializing local Faster-Whisper model ({target_model}) on {device} ({compute_type})...")
            # Disable symlink warnings on Windows to avoid clutter
            os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
            try:
                self.whisper_model = WhisperModel(
                    target_model, 
                    device=device, 
                    compute_type=compute_type,
                    cpu_threads=4
                )
                log.info(f"Local Faster-Whisper model ({target_model}) loaded successfully on {device}!")
            except Exception as load_err:
                log.warning(f"Could not load primary model '{target_model}': {load_err}. Falling back to 'small.en'...")
                try:
                    self.whisper_model = WhisperModel(
                        "small.en", 
                        device=device, 
                        compute_type=compute_type,
                        cpu_threads=4
                    )
                    log.info("Local Faster-Whisper fallback model (small.en) loaded successfully on {device}!")
                except Exception:
                    self.whisper_model = WhisperModel(
                        "base.en", 
                        device=device, 
                        compute_type=compute_type,
                        cpu_threads=4
                    )
                    log.info("Local Faster-Whisper fallback model (base.en) loaded successfully on {device}!")

            # Pre-warm CUDA forward pass to eliminate first-inference 1.2s JIT delay
            try:
                log.info("Pre-warming local Faster-Whisper on CUDA...")
                dummy_pcm = np.zeros(16000, dtype=np.float32)
                list(self.whisper_model.transcribe(dummy_pcm, language="en", beam_size=1)[0])
                log.info(f"Local Faster-Whisper model ({target_model}) fully pre-warmed and ready for sub-200ms inference!")
                self.model_ready.emit(target_model)
            except Exception as warm_err:
                log.warning(f"Whisper pre-warm warning: {warm_err}")
                self.model_ready.emit(target_model)
        except Exception as e:
            log.warning(f"Could not load local faster-whisper ({e}). Will use cloud STT fallback.")
            self.model_ready.emit("cloud")

    def stop(self):
        self._running = False
        self.wait()

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def _create_stream(self, gain_factor: float):
        """
        Attempts to open the best working microphone input stream across all Host APIs
        (DirectSound, WASAPI, MME) with automatic sample rate negotiation and mono downsampling.
        Returns (stream, stream_samplerate, stream_channels) or (None, None, None).
        """
        try:
            devices = sd.query_devices()
            hostapis = {i: api['name'] for i, api in enumerate(sd.query_hostapis())}
        except Exception as q_err:
            log.warning(f"Failed to query audio devices: {q_err}")
            devices = []
            hostapis = {}

        # Build prioritized candidate list:
        # Default device first, then WASAPI, then DirectSound, then MME.
        # Skip WDM-KS devices because they demand exclusive kernel streaming access.
        candidates = [(None, "Windows Default Input", 44100)]
        
        wasapi_cands = []
        dsound_cands = []
        mme_cands = []
        
        for idx, dev in enumerate(devices):
            if dev.get('max_input_channels', 0) <= 0:
                continue
            api_name = hostapis.get(dev.get('hostapi', -1), '').lower()
            if 'wdm-ks' in api_name:
                continue
            def_sr = int(dev.get('default_samplerate', 44100))
            item = (idx, f"{dev['name']} ({api_name})", def_sr)
            if 'wasapi' in api_name:
                wasapi_cands.append(item)
            elif 'directsound' in api_name:
                dsound_cands.append(item)
            elif 'mme' in api_name:
                mme_cands.append(item)

        candidates.extend(wasapi_cands)
        candidates.extend(dsound_cands)
        candidates.extend(mme_cands)

        for dev_idx, dev_desc, def_sr in candidates:
            sample_rates = []
            for sr in [16000, 48000, 44100, def_sr]:
                if sr > 0 and sr not in sample_rates:
                    sample_rates.append(sr)
            
            channels_list = [1, 2]

            for sr in sample_rates:
                for ch in channels_list:
                    blocksize = int(sr * FRAME_MS / 1000)
                    
                    def make_callback(capture_sr, capture_ch):
                        def callback(indata, frames, time_info, status):
                            if self._paused or getattr(self, "is_speaking", False) or getattr(self, "is_transcribing", False):
                                return  # Drop frames immediately while speaking or transcribing to prevent queue backlog
                            if status:
                                pass
                            if len(indata) == 0:
                                return
                            # Extract mono channel
                            if capture_ch > 1:
                                raw = indata[:, 0]
                            else:
                                raw = indata.flatten()
                            
                            # Resample / decimate to 16000 Hz if needed
                            if capture_sr == 16000:
                                resampled = raw
                            elif capture_sr == 48000:
                                resampled = raw[::3]
                            else:
                                x_old = np.linspace(0, 1, len(raw))
                                x_new = np.linspace(0, 1, FRAME_SAMPLES)
                                resampled = np.interp(x_new, x_old, raw).astype(np.int16)
                            
                            if len(resampled) != FRAME_SAMPLES:
                                if len(resampled) > FRAME_SAMPLES:
                                    resampled = resampled[:FRAME_SAMPLES]
                                else:
                                    resampled = np.pad(resampled, (0, FRAME_SAMPLES - len(resampled)))

                            if gain_factor != 1.0:
                                boosted = resampled.astype(np.float32) * gain_factor
                                np.clip(boosted, -32768.0, 32767.0, out=boosted)
                                self.audio_queue.put(boosted.astype(np.int16))
                            else:
                                self.audio_queue.put(resampled.copy())
                        return callback

                    try:
                        stream = sd.InputStream(
                            device=dev_idx,
                            samplerate=sr,
                            channels=ch,
                            dtype='int16',
                            blocksize=blocksize,
                            callback=make_callback(sr, ch)
                        )
                        log.info(f"Successfully opened microphone: {dev_desc} at {sr}Hz, {ch}ch")
                        return stream, sr, ch
                    except Exception:
                        continue

        return None, None, None

    def run(self):
        log.info("ListenerThread: run() started.")
        self._running = True
        
        gain_factor = float(os.environ.get("AUDIO_GAIN_BOOST", getattr(config, "AUDIO_GAIN_BOOST", 1.8)))

        # Persistent stream recovery loop: auto-reconnects on device lock, sleep, or stream drop
        while self._running:
            stream, stream_sr, stream_ch = self._create_stream(gain_factor)
            if stream is None:
                log.error("Could not open any audio input device! Retrying in 2 seconds...")
                self.error_occurred.emit("Could not open any audio input device. Retrying...")
                time.sleep(2.0)
                continue

            try:
                with stream:
                    import webrtcvad
                    vad_mode = int(os.environ.get("VAD_AGGRESSIVENESS", getattr(config, "VAD_AGGRESSIVENESS", 3)))
                    vad = webrtcvad.Vad(vad_mode)

                    # Initialize reliable baseline noise parameters immediately so mic is never deaf
                    noise_floor = 2.5
                    noise_std = 0.5
                    self._energy_threshold = float(os.environ.get("INITIAL_ENERGY_THRESHOLD", 5.0))
                    self._snr_gate = 14.0
                    self._min_speech_peak = 35.0
                    peak_ambient = 6.0

                    # If assistant is not currently speaking at startup, run a swift 0.3s background calibration.
                    # If assistant IS speaking (welcome greeting), DO NOT block! The robust baseline is instantly live.
                    if not getattr(self, "is_speaking", False):
                        time.sleep(0.08)
                        while not self.audio_queue.empty():
                            try: self.audio_queue.get_nowait()
                            except queue.Empty: break

                        ambient_rms = []
                        ambient_peaks = []
                        start_cal = time.time()
                        while time.time() - start_cal < 0.3 and self._running and not getattr(self, "is_speaking", False):
                            try:
                                data = self.audio_queue.get(timeout=0.04)
                                if len(data) > 0:
                                    rms = float(np.sqrt(np.mean(np.square(data, dtype=np.float32))))
                                    peak = float(np.percentile(np.abs(data), 98))
                                    ambient_rms.append(rms)
                                    ambient_peaks.append(peak)
                            except queue.Empty:
                                continue

                        if ambient_rms:
                            avg_ambient = float(np.mean(ambient_rms))
                            std_ambient = float(np.std(ambient_rms))
                            peak_ambient = float(np.percentile(ambient_peaks, 95)) if ambient_peaks else 6.0
                            noise_floor = min(6.0, max(1.5, avg_ambient))
                            noise_std = min(2.5, max(0.4, std_ambient))
                            self._energy_threshold = max(4.0, min(9.0, noise_floor + max(2.5, 1.8 * noise_std)))
                            self._snr_gate = max(self._energy_threshold * 1.2, max(peak_ambient * 1.15, 14.0))
                            self._min_speech_peak = max(35.0, self._snr_gate * 2.0)

                    log.info(f"Listener online: Noise Floor={noise_floor:.1f}, Threshold={self._energy_threshold:.1f}, SNR Gate={self._snr_gate:.1f}, Min Speech Peak={self._min_speech_peak:.1f}, VAD Level={vad_mode}")
                    self.calibration_finished.emit(noise_floor, self._energy_threshold)
                    print(json.dumps({"type": "speech_text", "value": "Ready! Listening for 'Hey Boopi' ✨"}), flush=True)

                    ring_buffer = collections.deque(maxlen=PRE_ROLL_FRAMES)
                    last_talking_time = 0
                    last_heartbeat = 0
                    
                    while self._running:
                        triggered = False
                        voiced_frames = []
                        silence_count = 0
                        ring_buffer.clear()
                        speech_detected = False

                        speaking_blocked_since = None
                        # Main loop for frame capture
                        while self._running:
                            from voice.speaker import is_speaker_playing

                            # If paused or assistant speaking, ignore audio input to prevent feedback loops
                            speaker_active = getattr(self, "is_speaking", False) or is_speaker_playing()
                            if self._paused or speaker_active:
                                if speaking_blocked_since is None:
                                    speaking_blocked_since = time.time()
                                elif time.time() - speaking_blocked_since > 2.0:
                                    # Verify if hardware audio playback is actually active
                                    if not is_speaker_playing():
                                        log.warning("[Listener Watchdog] Hardware playback ended but speech lock lingered. Auto-unmuting mic!")
                                        self.is_speaking = False
                                        self._paused = False
                                        speaking_blocked_since = None
                                
                                last_talking_time = time.time()
                                ring_buffer.clear()
                                triggered = False
                                voiced_frames.clear()
                                while not self.audio_queue.empty():
                                    try:
                                        self.audio_queue.get_nowait()
                                    except queue.Empty:
                                        break
                                time.sleep(0.04)
                                continue
                            else:
                                speaking_blocked_since = None
                              
                            # 0.25s acoustic cooldown after Bupi stops talking to avoid picking up speaker echo
                            if time.time() - last_talking_time < 0.25:
                                ring_buffer.clear()
                                triggered = False
                                voiced_frames.clear()
                                while not self.audio_queue.empty():
                                    try:
                                        self.audio_queue.get_nowait()
                                    except queue.Empty:
                                        break
                                time.sleep(0.04)
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
                                current_threshold *= 3.0

                            # Frame peak check: SNR gate rejects fan hum / electrical noise floor before running VAD
                            max_val = float(np.percentile(np.abs(data), 98)) if len(data) > 0 else 0.0
                            snr_gate = getattr(self, "_snr_gate", 14.0)

                            # VAD speech determination:
                            if rms > current_threshold and max_val >= snr_gate:
                                frame = data.flatten().tobytes()
                                try:
                                    is_vad = vad.is_speech(frame, SAMPLE_RATE)
                                except Exception:
                                    is_vad = False
                                # Fast, reliable dual-trigger: WebRTC VAD detects speech OR frame energy is clearly vocal
                                if is_vad or (rms > current_threshold * 1.35 and rms > 6.0):
                                    is_speech = True
                            else:
                                is_vad = False
                                is_speech = False

                            # Continuous ambient noise tracking when idle (dynamically adapts ONLY to genuine quiet ambient)
                            if not is_speech and not triggered and not getattr(self, "is_speaking", False) and rms < 5.0 and rms <= current_threshold:
                                noise_floor = 0.95 * noise_floor + 0.05 * rms
                                self._energy_threshold = max(4.0, min(9.0, noise_floor + max(2.5, 1.8 * noise_std)))
                                self._snr_gate = max(self._energy_threshold * 1.2, max(peak_ambient * 1.15, 14.0))
                                self._min_speech_peak = max(35.0, self._snr_gate * 2.0)

                            if not triggered:
                                # Standard VAD trigger when VAD thresholds met
                                ring_buffer.append((data.flatten().tobytes(), is_speech))
                                num_voiced = sum(1 for _, s in ring_buffer if s)
                                # Periodic heartbeat log every 3s in idle so mic health is logged
                                if not getattr(self, "is_speaking", False) and time.time() - last_heartbeat > 3.0:
                                    last_heartbeat = time.time()
                                    try:
                                        from logger import crash_log
                                        crash_log(f"[Mic Monitor] Live RMS={rms:.1f}, Threshold={current_threshold:.1f}, Voiced={num_voiced}/20")
                                    except Exception:
                                        pass

                                # 5 out of 20 frames = ~150ms of sustained speech initiates listening mode!
                                if num_voiced >= 5:
                                    triggered = True
                                    voiced_frames.extend([f for f, _ in ring_buffer])
                                    ring_buffer.clear()
                                    log.info("VAD Speech started...")
                                    self.listening_started.emit()
                                    print(json.dumps({"type": "speech_text", "value": "Listening... 🎙️"}), flush=True)
                            else:
                                # Once triggered, record voiced frames
                                voiced_frames.append(data.flatten().tobytes())
                                
                                # Silence detection:
                                # Determine if frame has genuine active vocal presence.
                                # WebRTC Vad(3) + energy gate ensures room fan/ambient hiss is NOT counted as active speech.
                                is_active_speech = (is_vad and max_val >= snr_gate and rms > current_threshold * 1.05) or (rms > current_threshold * 1.35 and rms > 6.0)
                                if is_active_speech:
                                    silence_count = 0
                                else:
                                    silence_count += 1
                                    # Natural conversational pause: SILENCE_FRAMES (~540ms) of silence
                                    if silence_count >= SILENCE_FRAMES:
                                        speech_detected = True
                                        break
                                  
                                # Max utterance limit of 15 seconds (prevents indefinite recording)
                                if len(voiced_frames) > int(15000 / FRAME_MS):
                                    speech_detected = True
                                    break

                        # Break thread if no longer running
                        if not self._running:
                            break

                        # Process transcription if VAD triggered speech window
                        if speech_detected:
                            # 1. Discard brief blips, clicks, or speaker echo without flashing Thinking or muting mic
                            if len(voiced_frames) < MIN_SPEECH_FRAMES:
                                log.info(f"Discarded short noise blip ({len(voiced_frames)} frames < {MIN_SPEECH_FRAMES}). Staying in idle.")
                                ring_buffer.clear()
                                voiced_frames.clear()
                                print(json.dumps({"type": "state", "value": "idle"}), flush=True)
                                continue

                            audio = np.frombuffer(b''.join(voiced_frames), dtype=np.int16)
                            orig_max = float(np.percentile(np.abs(audio), 98)) if len(audio) > 0 else 0.0
                            min_speech_peak = max(35.0, getattr(self, "_min_speech_peak", 35.0))

                            if orig_max < min_speech_peak:
                                log.info(f"Discarded low-energy blip without thinking (peak: {orig_max:.1f} < {min_speech_peak:.1f})")
                                ring_buffer.clear()
                                voiced_frames.clear()
                                print(json.dumps({"type": "state", "value": "idle"}), flush=True)
                                continue

                            # 2. Genuine speech confirmed: Now transition to thinking and process
                            log.info(f"Speech finished ({len(voiced_frames)} frames, peak={orig_max:.1f}), processing transcription...")
                            self.listening_stopped.emit()
                            print(json.dumps({"type": "speech_text", "value": "Thinking... 🤔"}), flush=True)
                            
                            self.is_transcribing = True
                            try:
                                self._transcribe_and_emit(audio)
                            except Exception as ex:
                                log.error(f"Error during transcription: {ex}")
                                self.transcription_ready.emit("")
                            finally:
                                self.is_transcribing = False
                                # Drain audio queue so buffer from during speech/transcription is discarded
                                while not self.audio_queue.empty():
                                    try:
                                        self.audio_queue.get_nowait()
                                    except queue.Empty:
                                        break

            except Exception as stream_err:
                if not self._running:
                    break
                log.warning(f"Audio input stream closed or error: {stream_err}. Reconnecting audio stream in 0.5s...")
                time.sleep(0.5)

    def _transcribe_and_emit(self, audio: np.ndarray):
        text = ""
        try:
            # Verify peak value before boosting to discard absolute silence
            orig_max = float(np.percentile(np.abs(audio), 98)) if len(audio) > 0 else 0.0
            cutoff = max(35.0, getattr(self, "_min_speech_peak", 35.0))
            if orig_max < cutoff:
                log.info(f"Discarded silent audio (peak: {orig_max:.1f} < {cutoff:.1f})")
                return

            # Soft peak normalization for quiet microphones (safe max 15x boost)
            if 0 < orig_max < 22000:
                gain = min(22000.0 / orig_max, 15.0)
                log.info(f"Soft peak normalization: peak={orig_max:.1f}, gain boost={gain:.2f}x")
                audio_boosted = audio.astype(np.float32) * gain
                np.clip(audio_boosted, -32768.0, 32767.0, out=audio_boosted)
                audio_gain = audio_boosted.astype(np.int16)
            else:
                audio_gain = audio

            # Normalize float32 1D array for Faster-Whisper
            audio_norm = audio_gain.flatten().astype(np.float32) / 32768.0
            
            # Generate WAV bytes in memory for cloud STT if enabled
            wav_bytes = None
            use_cloud = getattr(config, "USE_CLOUD_STT", True) or (os.getenv("USE_CLOUD_STT", "true").lower() == "true")
            if use_cloud:
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

            # 1. Primary Cloud STT: Gemini 2.5 Flash (accurate Indian/English/Hinglish) or Groq Whisper
            if use_cloud and wav_bytes:
                preferred_stt = os.getenv("CLOUD_STT_PROVIDER", "groq").lower()
                if preferred_stt == "groq":
                    groq_keys = get_groq_keys()
                    if groq_keys:
                        text = self._groq_stt(wav_bytes, groq_keys)
                    if not text:
                        google_keys = get_google_keys()
                        if google_keys:
                            text = self._gemini_stt(wav_bytes, google_keys)
                else:
                    google_keys = get_google_keys()
                    if google_keys:
                        text = self._gemini_stt(wav_bytes, google_keys)
                    if not text:
                        groq_keys = get_groq_keys()
                        if groq_keys:
                            text = self._groq_stt(wav_bytes, groq_keys)

            # 2. Offline Fallback: Local Faster-Whisper (base model, 100% offline, GPU/CPU)
            if not text:
                if not self.whisper_model:
                    try:
                        self._init_whisper()
                    except Exception as ex:
                        log.error(f"Could not initialize local Whisper: {ex}")
                        
                if self.whisper_model:
                    try:
                        # Enforce language="en" so model transcribes directly in English
                        segments, info = self.whisper_model.transcribe(
                            audio_norm, 
                            language="en", 
                            initial_prompt=PROMPT_CONTEXT, 
                            condition_on_previous_text=False,
                            beam_size=2,
                            best_of=2,
                            temperature=0.0,
                            no_speech_threshold=0.6,
                            compression_ratio_threshold=2.4,
                            log_prob_threshold=-1.0,
                            vad_filter=False
                        )
                        text = " ".join([segment.text for segment in segments]).strip()
                        log.info(f"Local Faster-Whisper Transcription: '{text}'")
                    except Exception as e:
                        log.warning(f"Local Faster-Whisper transcription error: {e}")
                        text = ""

            if text:
                # Hallucination Filtering: Check pattern-based and common hallucinations
                if is_hallucinated_output(text):
                    log.info(f"Filtered hallucination via repetitive pattern check: '{text}'")
                    text = ""
                else:
                    clean_text = text.replace(",", "").replace(".", "").strip().lower()
                    hallucinations = [
                        "thank you for watching", "thanks for watching", "please subscribe", 
                        "like and subscribe", "screencast", "see you next time", "see you in the next video",
                        "bupi is an autonomous robot assistant", "hvað er hann", "hva er hann"
                    ]
                    if any(h in clean_text for h in hallucinations) or (clean_text in ["...", "thank you", "thanks", "bye", "bye bye", "goodbye", "you", "hva er hann", "hvað er hann"]):
                        log.info(f"Filtered stock Whisper hallucination: '{text}'")
                        text = ""
                    elif len(clean_text) <= 1:
                        text = ""
        except Exception as ex:
            log.error(f"Unhandled error in _transcribe_and_emit: {ex}")
        finally:
            self.is_transcribing = False
            self.transcription_ready.emit(text)

    def _groq_stt(self, wav_bytes, keys=None):
        if keys is None:
            keys = get_groq_keys()
        if not keys:
            return ""
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
                model_name = os.environ.get("GROQ_STT_MODEL", getattr(config, "GROQ_STT_MODEL", "whisper-large-v3-turbo"))
                data = {
                    "model": model_name,
                    "prompt": "Hey Boopi, how are you? Hello Bupi, what's up? Move forward, stop.",
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

    def _gemini_stt(self, wav_bytes, keys=None):
        if keys is None:
            keys = get_google_keys()
        if not keys:
            return ""
        log.info("Running cloud transcription via Gemini 2.5 Flash REST API...")
        import requests
        import base64
        
        b64_audio = base64.b64encode(wav_bytes).decode('utf-8')
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": "audio/wav",
                                "data": b64_audio
                            }
                        },
                        {
                            "text": f"Transcribe this speech audio file accurately. Output ONLY the verbatim spoken transcription, with no extra commentary or markdown. Vocabulary context: {PROMPT_CONTEXT}"
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.0,
                "maxOutputTokens": 120
            }
        }
        
        for idx, key in enumerate(keys):
            try:
                log.info(f"Trying Gemini STT key {idx+1}/{len(keys)}...")
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
                response = requests.post(url, json=payload, timeout=5.0)
                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            transcription = parts[0].get("text", "").strip()
                            log.info(f"Gemini API Transcription Success: '{transcription}'")
                            return transcription
                else:
                    log.warning(f"Gemini STT key {idx+1} failed with status {response.status_code}: {response.text[:120]}")
            except requests.exceptions.Timeout:
                log.warning(f"Gemini STT key {idx+1} timed out (5s). Cascading to next key / Groq.")
                continue
            except Exception as e:
                log.warning(f"Gemini STT failed with key {idx+1}: {e}")
              
        return ""
