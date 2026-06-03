from PyQt6.QtCore import QThread, pyqtSignal
import sounddevice as sd, numpy as np, collections
import warnings
warnings.filterwarnings("ignore", message=".*FP16 is not supported on CPU.*")

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)
VAD_AGGRESSIVENESS = 3
SILENCE_FRAMES = 25 # Wait 750ms to prevent cutting the user off mid-sentence
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
        from faster_whisper import WhisperModel
        # Using "small" model size (~244M params) for significantly higher accuracy while maintaining low CPU latency!
        print("[Whisper] Loading local faster-whisper small model for high-accuracy local transcription...", flush=True)
        self._model = WhisperModel("small", device="cpu", compute_type="int8")
        print("[Whisper] Model loaded.")

    def run(self):
        self._running = True
        try:
            stream = None
            try:
                stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', blocksize=FRAME_SAMPLES)
            except Exception as e:
                safe_e = str(e).encode('ascii', 'ignore').decode('ascii')
                print(f"From Python: [Listener Warning] Default device failed: {safe_e}. Trying fallbacks...", flush=True)
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
                
                import webrtcvad
                vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
                
                print("From Python: [Listener] WebRTC VAD Initialized. Background noise will be actively cancelled.", flush=True)

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

                    while self._running and not self._paused:
                        data, _ = stream.read(FRAME_SAMPLES)
                        
                        # Energy based filtering before running heavy checks
                        rms = np.sqrt(np.mean(np.square(data, dtype=np.float32)))
                        is_speech = False
                        
                        if rms > self._energy_threshold:
                            # Apply moderate software gain
                            data_float = data.astype(np.float32) * 10.0
                            np.clip(data_float, -32768, 32767, out=data_float)
                            amplified_data = data_float.astype(np.int16)
                            frame = amplified_data.flatten().tobytes()
                            
                            # WebRTC VAD voice activity check
                            try:
                                is_speech = vad.is_speech(frame, SAMPLE_RATE)
                            except Exception:
                                is_speech = False
                        
                        if not triggered:
                            ring_buffer.append((data.flatten().tobytes(), is_speech))
                            num_voiced = sum(1 for _, s in ring_buffer if s)
                            if num_voiced >= 0.4 * ring_buffer.maxlen:
                                triggered = True
                                voiced_frames.extend([f for f, _ in ring_buffer])
                                ring_buffer.clear()
                        else:
                            voiced_frames.append(data.flatten().tobytes())
                            if is_speech:
                                silence_count = 0
                            if not is_speech:
                                silence_count += 1
                                if silence_count > SILENCE_FRAMES:
                                    speech_detected = True
                                    break
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

        except Exception as e:
            self.error_occurred.emit(str(e))

    def _transcribe(self, audio: np.ndarray):
        self._paused = True
        
        # Apply software gain boost of 8.0 to handle quiet/low-gain microphones on Windows
        audio_boosted = audio.astype(np.float32) * 8.0
        np.clip(audio_boosted, -32768, 32767, out=audio_boosted)
        audio = audio_boosted.astype(np.int16)
        
        # Local peak energy check with relaxed threshold (300 with 8x gain means unamplified peak >= 37.5)
        max_val = np.max(np.abs(audio)) if len(audio) > 0 else 0
        if max_val < 300:
            print(f"From Python: [Listener] Discarded silent audio (peak: {max_val} is below threshold 300)", flush=True)
            self.transcription_ready.emit("")
            return

        audio_f32 = audio.astype(np.float32) / 32768.0
        
        # Give whisper context to heavily bias towards names, commands, and app functions we care about
        prompt = "Bupi, shift to Mode 2, shift to Mode 1, Mode 2, Mode 1, display readings, show sensor values, highest reading, MQ2 gas sensor, LCD screen, relay, turn on, turn off, message Chintu on WhatsApp, send email, write draft in Notepad, YouTube, OpenRouter, Claude, summarize, rewrite."
        segments, info = self._model.transcribe(audio_f32, language="en", initial_prompt=prompt, condition_on_previous_text=False)
        text = "".join([segment.text for segment in segments]).strip()
        
        # Filter out common Whisper hallucinations for silence
        clean_text = text.replace(",", "").replace(".", "").strip().lower()
        clean_prompt = prompt.replace(",", "").replace(".", "").strip().lower()
        
        hallucinations = ["thank you", "thanks for watching", "please subscribe", "thank you.", "thank you very much.", "screencast", "goodbye", "goodbye."]
        
        # Check if the transcription is just a hallucination repeating parts of the prompt
        # CPU Whisper tends to regurgitate prompt items like 'Chintu on WhatsApp, send email, write draft in Notepad' when the room is silent
        prompt_words = [w for w in clean_prompt.split() if len(w) > 3]
        matched_words = sum(1 for w in prompt_words if w in clean_text)
        prompt_density = (matched_words / len(prompt_words)) if prompt_words else 0
        
        is_exact_prompt = (clean_text == clean_prompt) or (prompt_density > 0.6 and len(clean_text) > 40)
        is_hallucination = any(h in clean_text for h in hallucinations) or is_exact_prompt
        
        if is_hallucination or (len(clean_text) <= 2 and clean_text != "hi" and clean_text != "go"):
            print(f"From Python: [Listener] Filtered silence/hallucination (prompt density: {prompt_density:.2f}, exact prompt: {is_exact_prompt})", flush=True)
            text = ""

        self.transcription_ready.emit(text)

    def stop(self):
        self._running = False

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False
