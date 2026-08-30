import os
import sys
import time
import queue
import threading
import asyncio
import numpy as np
import sounddevice as sd

class VoiceService:
    """
    A unified service class for speech-to-text (STT) and text-to-speech (TTS).
    Can be easily imported and used in Python command-line or GUI projects.
    """
    def __init__(self, voice="en-US-AnaNeural", sample_rate=16000):
        self.voice = voice
        self.sample_rate = sample_rate
        self.local_whisper = None
        self._playback_thread = None
        self._tts_queue = queue.Queue()
        self._playing = False
        
        # Load local model lazily if Groq API keys are not detected
        if not self._get_groq_keys():
            threading.Thread(target=self._lazy_load_whisper, daemon=True).start()

    def _get_groq_keys(self):
        from dotenv import load_dotenv
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        load_dotenv(os.path.join(parent_dir, ".env"))
        
        keys = []
        if os.environ.get("GROQ_API_KEY"):
            keys.append(os.environ.get("GROQ_API_KEY"))
        for i in range(2, 11):
            k = os.environ.get(f"GROQ_API_KEY_{i}")
            if k:
                keys.append(k)
        return keys

    def _lazy_load_whisper(self):
        try:
            from faster_whisper import WhisperModel
            print("[VoiceService] No Groq API keys found. Pre-loading local Whisper model in background...", flush=True)
            self.local_whisper = WhisperModel("small", device="cpu", compute_type="int8")
            print("[VoiceService] Local Whisper model loaded successfully.", flush=True)
        except Exception as e:
            print(f"[VoiceService Warning] Failed to lazy load Whisper: {e}", flush=True)

    def listen(self, duration_limit=15):
        """
        Listens on the default microphone, waits for speech to end,
        and returns the transcribed text. Blocks until completed.
        """
        import webrtcvad
        import collections
        
        # VAD settings
        frame_ms = 30
        frame_samples = int(self.sample_rate * frame_ms / 1000)
        vad = webrtcvad.Vad(2)
        
        try:
            stream = sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='int16', blocksize=frame_samples)
            stream.start()
        except Exception as e:
            print(f"[VoiceService ERROR] Could not start audio stream: {e}")
            return ""

        # Calibrate energy threshold
        print("[VoiceService] Calibrating microphone for 1s...")
        ambient_frames = []
        for _ in range(int(1000 / frame_ms)):
            data, _ = stream.read(frame_samples)
            rms = np.sqrt(np.mean(np.square(data, dtype=np.float32)))
            ambient_frames.append(rms)
        avg_ambient = sum(ambient_frames) / len(ambient_frames) if ambient_frames else 10.0
        energy_threshold = min(max(15, avg_ambient * 1.25), 45.0)
        
        ring_buffer = collections.deque(maxlen=20)
        triggered = False
        voiced_frames = []
        silence_count = 0
        silence_limit = 25 # ~750ms
        
        print("[VoiceService] Listening...")
        
        start_time = time.time()
        text = ""
        
        try:
            while (time.time() - start_time) < duration_limit:
                data, _ = stream.read(frame_samples)
                rms = np.sqrt(np.mean(np.square(data, dtype=np.float32)))
                
                is_speech = False
                if rms > energy_threshold:
                    max_val = np.percentile(np.abs(data), 98) if len(data) > 0 else 0
                    if 0 < max_val < 24000:
                        gain = min(24000.0 / max_val, 10.0)
                        data_float = data.astype(np.float32) * gain
                        np.clip(data_float, -32768, 32767, out=data_float)
                        amplified = data_float.astype(np.int16)
                    else:
                        amplified = data
                        
                    frame_bytes = amplified.flatten().tobytes()
                    try:
                        is_speech = vad.is_speech(frame_bytes, self.sample_rate)
                    except:
                        is_speech = False
                        
                if not triggered:
                    ring_buffer.append((data.flatten().tobytes(), is_speech))
                    num_voiced = sum(1 for _, s in ring_buffer if s)
                    if num_voiced >= 0.4 * ring_buffer.maxlen:
                        triggered = True
                        print("[VoiceService] Speech detected...")
                        voiced_frames.extend([f for f, _ in ring_buffer])
                        ring_buffer.clear()
                else:
                    voiced_frames.append(data.flatten().tobytes())
                    if is_speech:
                        silence_count = 0
                    else:
                        silence_count += 1
                        
                    if silence_count > silence_limit or len(voiced_frames) > int(15000 / frame_ms):
                        print("[VoiceService] Processing audio...")
                        break
        except Exception as e:
            print(f"[VoiceService ERROR] Exception in listening loop: {e}")
        finally:
            stream.stop()
            stream.close()

        if len(voiced_frames) >= 10:
            audio_np = np.frombuffer(b''.join(voiced_frames), dtype=np.int16)
            from listener_demo import transcribe_audio
            text = transcribe_audio(audio_np, self.local_whisper)
            
        return text

    def speak(self, text):
        """
        Synthesizes the text to speech and plays it back synchronously.
        Blocks until playback is complete.
        """
        if not text or not text.strip():
            return
            
        temp_file = f"temp_speech_service_{int(time.time())}.mp3"
        
        # Async generation runner
        async def run_tts():
            import edge_tts
            communicate = edge_tts.Communicate(text, self.voice)
            await communicate.save(temp_file)
            
        try:
            # edge-tts is fully async, run it in loop
            asyncio.run(run_tts())
            
            # Play using ffplay subprocess
            from speaker_demo import play_audio
            if os.path.exists(temp_file):
                self._playing = True
                play_audio(temp_file)
        except Exception as e:
            print(f"[VoiceService ERROR] Failed to perform TTS: {e}")
        finally:
            self._playing = False
            if os.path.exists(temp_file):
                try: os.remove(temp_file)
                except: pass

    def speak_async(self, text):
        """
        Speaks the text asynchronously in a background thread.
        Does not block the calling thread.
        """
        t = threading.Thread(target=self.speak, args=(text,), daemon=True)
        t.start()
        return t

    def is_speaking(self):
        """Returns True if audio playback is actively running."""
        return self._playing
