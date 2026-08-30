import os
import sys
import collections
import string
import wave
import io
import requests
import warnings
import numpy as np
import sounddevice as sd

# Suppress FP16 warning on CPU for faster-whisper
warnings.filterwarnings("ignore", message=".*FP16 is not supported on CPU.*")

# Audio Config
SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000) # 480 samples
VAD_AGGRESSIVENESS = 2
SILENCE_FRAMES = 25      # Wait ~750ms of silence before stopping transcription
MIN_SPEECH_FRAMES = 10   # Reject audio shorter than 300ms
PRE_ROLL_FRAMES = 20     # Keep 600ms of audio before speech begins

PROMPT_CONTEXT = (
    "Boopi, Bupi, Boopy, Boopie, how are you, shift to Mode 2, shift to Mode 1, Mode 2, Mode 1, "
    "display readings, show sensor values, highest reading, MQ2 gas sensor, LCD screen, relay, "
    "turn on, turn off, message Chintu on WhatsApp, send email, write draft in Notepad, "
    "YouTube, OpenRouter, Claude, summarize, rewrite."
)

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
    from dotenv import load_dotenv
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(os.path.join(parent_dir, ".env"))
    
    groq_keys = []
    if os.environ.get("GROQ_API_KEY"):
        groq_keys.append(os.environ.get("GROQ_API_KEY"))
    for i in range(2, 11):
        key = os.environ.get(f"GROQ_API_KEY_{i}")
        if key:
            groq_keys.append(key)
    return groq_keys

def transcribe_audio(audio: np.ndarray, local_model=None):
    # Verify peak value before boosting to discard absolute silence
    orig_max = np.percentile(np.abs(audio), 98) if len(audio) > 0 else 0
    if orig_max < 38:
        print(f"\n[STT] Discarded silent audio (peak: {orig_max} < 38)")
        return ""

    # Soft peak normalization for quiet microphones
    if 0 < orig_max < 24000:
        gain = min(24000.0 / orig_max, 8.0)
        audio_boosted = audio.astype(np.float32) * gain
        np.clip(audio_boosted, -32768, 32767, out=audio_boosted)
        audio = audio_boosted.astype(np.int16)

    groq_keys = get_groq_keys()
    text = ""
    success = False

    if groq_keys:
        # Generate WAV in-memory
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2) # 16-bit PCM
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(audio.tobytes())
        wav_bytes = wav_buffer.getvalue()

        for key in groq_keys:
            try:
                print(f"\n[STT] Requesting Groq Whisper API (key: {key[:6]}...)...", end="", flush=True)
                files = {'file': ('speech.wav', wav_bytes, 'audio/wav')}
                data = {
                    'model': 'whisper-large-v3',
                    'language': 'en',
                    'prompt': PROMPT_CONTEXT
                }
                headers = {'Authorization': f'Bearer {key}'}
                r = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions", 
                    headers=headers, 
                    files=files, 
                    data=data, 
                    timeout=4.0
                )
                if r.status_code == 200:
                    text = r.json().get("text", "").strip()
                    success = True
                    break
                else:
                    print(f" Error {r.status_code}: {r.text}")
            except Exception as e:
                print(f" Request failed: {e}")
                
    if not success:
        print("\n[STT] Falling back to local CPU Whisper model...")
        if local_model is None:
            from faster_whisper import WhisperModel
            print("[STT] Loading local model 'small' (device: cpu, compute_type: int8)...")
            local_model = WhisperModel("small", device="cpu", compute_type="int8")
        
        audio_f32 = audio.astype(np.float32) / 32768.0
        segments, _ = local_model.transcribe(
            audio_f32, 
            language="en", 
            initial_prompt=PROMPT_CONTEXT, 
            condition_on_previous_text=False
        )
        text = "".join([segment.text for segment in segments]).strip()

    # Hallucination Filtering
    clean_text = text.replace(",", "").replace(".", "").strip().lower()
    clean_prompt = PROMPT_CONTEXT.replace(",", "").replace(".", "").strip().lower()
    
    hallucinations = ["thank you", "thanks for watching", "please subscribe", "thank you.", "screencast", "goodbye"]
    
    prompt_words = [w for w in clean_prompt.split() if len(w) > 3]
    matched_words = sum(1 for w in prompt_words if w in clean_text)
    prompt_density = (matched_words / len(prompt_words)) if prompt_words else 0
    
    is_exact_prompt = (clean_text == clean_prompt) or (prompt_density > 0.6 and len(clean_text) > 40)
    is_hallucination = any(h in clean_text for h in hallucinations) or is_exact_prompt or is_hallucinated_output(text)
    
    if is_hallucination or (len(clean_text) <= 2 and clean_text not in ["hi", "go"]):
        print(f"[STT] Filtered silence/hallucination (prompt density: {prompt_density:.2f}, robust check: {is_hallucinated_output(text)})")
        return ""

    return text

def main():
    print("=== Standalone Speech-to-Text Listener ===")
    
    # Check WebRTC VAD
    try:
        import webrtcvad
        vad = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        print("[VAD] WebRTC VAD successfully loaded.")
    except ImportError:
        print("[ERROR] WebRTC VAD is not installed. Run install.bat first.")
        sys.exit(1)
        
    local_whisper = None
    # Pre-load Whisper if no Groq keys exist to avoid startup lag on first query
    groq_keys = get_groq_keys()
    if not groq_keys:
        from faster_whisper import WhisperModel
        print("[STT] No Groq keys. Loading local 'small' CPU model now to avoid capture delay...")
        local_whisper = WhisperModel("small", device="cpu", compute_type="int8")
        print("[STT] Local model ready.")
        
    # Open Stream
    try:
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', blocksize=FRAME_SAMPLES)
        stream.start()
        print("[Audio] Audio input stream started successfully.")
    except Exception as e:
        print(f"[ERROR] Could not start audio input stream: {e}")
        sys.exit(1)

    # Ambient Calibration
    print("[Audio] Calibrating microphone for ambient noise (1 second)...")
    ambient_frames = []
    for _ in range(int(1000 / FRAME_MS)):
        data, _ = stream.read(FRAME_SAMPLES)
        rms = np.sqrt(np.mean(np.square(data, dtype=np.float32)))
        ambient_frames.append(rms)
        
    avg_ambient = sum(ambient_frames) / len(ambient_frames) if ambient_frames else 10.0
    energy_threshold = min(max(15, avg_ambient * 1.25), 45.0)
    print(f"[Audio] Calibration done. Ambient noise: {avg_ambient:.1f}, Energy Threshold: {energy_threshold:.1f}")

    ring_buffer = collections.deque(maxlen=PRE_ROLL_FRAMES)
    triggered = False
    voiced_frames = []
    silence_count = 0

    print("\n>>> Listening... Speak into the microphone. Press Ctrl+C to exit. <<<\n")
    
    try:
        while True:
            data, _ = stream.read(FRAME_SAMPLES)
            rms = np.sqrt(np.mean(np.square(data, dtype=np.float32)))
            
            is_speech = False
            if rms > energy_threshold:
                # Normalization
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
                    is_speech = vad.is_speech(frame_bytes, SAMPLE_RATE)
                except Exception:
                    is_speech = False

            if not triggered:
                ring_buffer.append((data.flatten().tobytes(), is_speech))
                num_voiced = sum(1 for _, s in ring_buffer if s)
                if num_voiced >= 0.4 * ring_buffer.maxlen:
                    triggered = True
                    print("[VAD] Speech started detected...", end="", flush=True)
                    voiced_frames.extend([f for f, _ in ring_buffer])
                    ring_buffer.clear()
            else:
                voiced_frames.append(data.flatten().tobytes())
                if is_speech:
                    silence_count = 0
                else:
                    silence_count += 1
                    
                # Break on long silence or maximum length of 15 seconds
                if silence_count > SILENCE_FRAMES or len(voiced_frames) > int(15000 / FRAME_MS):
                    print(" Finished.", flush=True)
                    if len(voiced_frames) >= MIN_SPEECH_FRAMES:
                        audio_np = np.frombuffer(b''.join(voiced_frames), dtype=np.int16)
                        text = transcribe_audio(audio_np, local_whisper)
                        if text:
                            print(f"\n[Transcribed] >>> \"{text}\" <<<\n")
                        else:
                            print("\n[Transcribed] (Filtered/No Speech)\n")
                    else:
                        print("[VAD] Speech too short, discarded.")
                    
                    # Reset state
                    triggered = False
                    voiced_frames.clear()
                    silence_count = 0
                    ring_buffer.clear()
                    print(">>> Listening... <<<")
                    
    except KeyboardInterrupt:
        print("\nStopping listener...")
    finally:
        stream.stop()
        stream.close()
        print("Goodbye!")

if __name__ == "__main__":
    main()
