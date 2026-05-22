from PyQt6.QtCore import QThread, pyqtSignal
import sounddevice as sd, numpy as np, collections
import warnings
warnings.filterwarnings("ignore", message=".*FP16 is not supported on CPU.*")

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)
VAD_AGGRESSIVENESS = 2
SILENCE_FRAMES = 30 # Reduced to ~0.9 seconds to vastly improve response time
MIN_SPEECH_FRAMES = 10
PRE_ROLL_FRAMES = 10

class ListenerThread(QThread):
    transcription_ready = pyqtSignal(str)
    listening_started   = pyqtSignal()
    listening_stopped   = pyqtSignal()
    error_occurred      = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._running = False
        self._paused = False
        self._energy_threshold = 800
        from faster_whisper import WhisperModel
        print("[Whisper] Loading faster-whisper small model for better accent recognition...", flush=True)
        self._model = WhisperModel("small", device="cpu", compute_type="int8")
        print("[Whisper] Model loaded.")

    def run(self):
        self._running = True
        try:
            stream = None
            try:
                stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', blocksize=FRAME_SAMPLES)
            except Exception as e:
                print(f"From Python: [Listener Warning] Default device failed: {e}. Trying fallbacks...", flush=True)
                for i, dev in enumerate(sd.query_devices()):
                    if dev['max_input_channels'] > 0:
                        try:
                            stream = sd.InputStream(device=i, samplerate=SAMPLE_RATE, channels=1, dtype='int16', blocksize=FRAME_SAMPLES)
                            print(f"From Python: [Listener] Selected fallback device {i}: {dev['name']}", flush=True)
                            break
                        except Exception:
                            stream = None
                            continue
            
            if stream is None:
                raise Exception("Could not open any audio input device.")

            with stream:
                
                # Dynamic microphone calibration (1 second) to handle loud laptop fans/AC
                ambient_frames = []
                print("From Python: [Listener] Calibrating microphone for 1 second...", flush=True)
                for _ in range(int(1000 / FRAME_MS)):
                    data, _ = stream.read(FRAME_SAMPLES)
                    if len(data) == 0: continue
                    rms = np.sqrt(np.mean(np.square(data, dtype=np.float32)))
                    ambient_frames.append(rms)
                
                if ambient_frames:
                    avg_ambient = sum(ambient_frames) / len(ambient_frames)
                    # Relaxed multiplier so normal conversational volume triggers the mic
                    self._energy_threshold = max(30, avg_ambient * 1.5)
                print(f"From Python: [Listener] Calibration done. Noise: {avg_ambient:.0f}, Threshold: {self._energy_threshold:.0f}", flush=True)

                ring_buffer = collections.deque(maxlen=PRE_ROLL_FRAMES)
                
                while self._running:
                    if self._paused:
                        stream.read(FRAME_SAMPLES)
                        continue
                    
                    self.listening_started.emit()
                    triggered = False
                    voiced_frames = []
                    silence_count = 0
                    ring_buffer.clear()
                    
                    speech_detected = False
                    frames_since_log = 0
                    max_rms_log = 0

                    while self._running and not self._paused:
                        data, _ = stream.read(FRAME_SAMPLES)
                        frame = data.flatten().tobytes()
                        # Energy based VAD
                        rms = np.sqrt(np.mean(np.square(data, dtype=np.float32)))
                        is_speech = rms > self._energy_threshold
                        
                        max_rms_log = max(max_rms_log, rms)
                        frames_since_log += 1
                        if frames_since_log > int(2000 / FRAME_MS):
                            if not triggered:
                                print(f"From Python: [Listener Debug] Waiting for speech. Max RMS last 2s: {max_rms_log:.0f} (Threshold: {self._energy_threshold:.0f})", flush=True)
                            max_rms_log = 0
                            frames_since_log = 0

                        if not triggered:
                            ring_buffer.append((frame, is_speech))
                            num_voiced = sum(1 for _, s in ring_buffer if s)
                            # Relaxed sensitivity so it triggers much faster and doesn't require sustained loud audio
                            if num_voiced >= 0.3 * ring_buffer.maxlen:
                                triggered = True
                                voiced_frames.extend([f for f, _ in ring_buffer])
                                ring_buffer.clear()
                        else:
                            voiced_frames.append(frame)
                            if is_speech:
                                silence_count = 0
                            if not is_speech:
                                silence_count += 1
                                if silence_count > SILENCE_FRAMES:
                                    speech_detected = True
                                    break
                            # Cap maximum recording length to ~15 seconds to prevent infinite noise loops
                            if len(voiced_frames) > int(15000 / FRAME_MS):
                                speech_detected = True
                                break
                    
                    if speech_detected:
                        if len(voiced_frames) >= MIN_SPEECH_FRAMES:
                            audio = np.frombuffer(b''.join(voiced_frames), dtype=np.int16)
                            self.listening_stopped.emit()
                            self._transcribe(audio)
                    else:
                        if not self._running:
                            break
                        # If we broke out due to _paused, continue loop

        except Exception as e:
            self.error_occurred.emit(str(e))

    def _transcribe(self, audio: np.ndarray):
        self._paused = True # Auto-pause while transcribing and processing
        audio_f32 = audio.astype(np.float32) / 32768.0
        
        # Give whisper context to heavily bias towards names and app functions we care about
        prompt = "Bupi, message hi to Chintu on WhatsApp, send, email, PDF, Document, Notepad, YouTube, OpenRouter, Claude, summarize, rewrite."
        segments, info = self._model.transcribe(audio_f32, language="en", initial_prompt=prompt, condition_on_previous_text=False)
        text = "".join([segment.text for segment in segments]).strip()
        
        # Filter out common Whisper hallucinations for silence
        clean_text = text.replace(",", "").replace(".", "").strip().lower()
        clean_prompt = prompt.replace(",", "").replace(".", "").strip().lower()
        
        hallucinations = ["thank you", "thanks for watching", "please subscribe"]
        
        if clean_text == clean_prompt or any(h in clean_text for h in hallucinations):
            print("From Python: [Whisper] Filtered hallucination.", flush=True)
            text = ""
            
        # Filter out if the text is just a few words from the prompt (hallucination)
        prompt_words = set(clean_prompt.split())
        text_words = set(clean_text.split())
        if len(text_words) > 0 and len(text_words) <= 5 and text_words.issubset(prompt_words):
            print(f"From Python: [Whisper] Filtered prompt hallucination: {text}", flush=True)
            text = ""
            
        self.transcription_ready.emit(text)

    def stop(self):
        self._running = False

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False
