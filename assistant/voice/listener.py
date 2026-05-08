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
        import whisper
        print("[Whisper] Loading advanced base model for better accuracy...", flush=True)
        self._model = whisper.load_model("base.en")  # Upgraded from tiny to base for much better NLP
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
                    self._energy_threshold = max(150, avg_ambient * 1.15)
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

                    while self._running and not self._paused:
                        data, _ = stream.read(FRAME_SAMPLES)
                        frame = data.flatten().tobytes()
                        # Energy based VAD
                        rms = np.sqrt(np.mean(np.square(data, dtype=np.float32)))
                        is_speech = rms > self._energy_threshold

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
                            else:
                                silence_count += 1
                                if silence_count > SILENCE_FRAMES:
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
        prompt = "Bupi, PDF, Document, WhatsApp, Notepad, OpenRouter, Claude, summarize, rewrite."
        result = self._model.transcribe(audio_f32, language="en", fp16=False, initial_prompt=prompt)
        text = result["text"].strip()
        self.transcription_ready.emit(text)

    def stop(self):
        self._running = False

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False
