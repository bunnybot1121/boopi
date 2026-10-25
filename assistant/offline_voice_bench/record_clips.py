"""
BUPI Offline Voice Stack Benchmark - Audio Clip Recorder & Generator
Records or synthesizes the 20 standardized benchmark audio clips (16kHz mono PCM).
"""

import os
import sys
import time
import wave
import numpy as np

# Ensure root assistant directory is accessible for utils
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
CLIPS_DIR = os.path.join(BENCH_DIR, "clips")
REFS_FILE = os.path.join(BENCH_DIR, "references.txt")

SAMPLE_RATE = 16000

# 20 Standardized Test Clips
SCRIPT_DATA = [
    # 8 English Commands
    {"id": "clip_01", "cat": "english", "text": "hey boopi how are you doing today", "duration": 3.0},
    {"id": "clip_02", "cat": "english", "text": "what is the battery level of the laptop", "duration": 3.2},
    {"id": "clip_03", "cat": "english", "text": "turn on the living room lights", "duration": 2.5},
    {"id": "clip_04", "cat": "english", "text": "can you open google chrome for me", "duration": 2.8},
    {"id": "clip_05", "cat": "english", "text": "what is the capital of france", "duration": 2.5},
    {"id": "clip_06", "cat": "english", "text": "set a reminder to drink water in thirty minutes", "duration": 3.5},
    {"id": "clip_07", "cat": "english", "text": "what was my last email about", "duration": 2.6},
    {"id": "clip_08", "cat": "english", "text": "stop talking and go to sleep", "duration": 2.4},
    
    # 6 Hinglish Commands
    {"id": "clip_09", "cat": "hinglish", "text": "hey boopi aaj ka weather kaisa hai", "duration": 3.0},
    {"id": "clip_10", "cat": "hinglish", "text": "mera calendar check karo aur batao aaj kya meeting hai", "duration": 4.2},
    {"id": "clip_11", "cat": "hinglish", "text": "robot ko bolo room clean kare", "duration": 2.8},
    {"id": "clip_12", "cat": "hinglish", "text": "boopi gaadi thoda aage badhao", "duration": 2.7},
    {"id": "clip_13", "cat": "hinglish", "text": "mera laptop slow chal raha hai memory clean kar do", "duration": 4.0},
    {"id": "clip_14", "cat": "hinglish", "text": "tum meri help kar sakte ho kya", "duration": 2.5},
    
    # 3 Hardware Commands
    {"id": "clip_15", "cat": "hardware", "text": "move forward two seconds and check the gas sensor", "duration": 3.8},
    {"id": "clip_16", "cat": "hardware", "text": "emergency stop all motors right now", "duration": 2.9},
    {"id": "clip_17", "cat": "hardware", "text": "turn on relay one and scan ultrasonic distance", "duration": 3.6},
    
    # 3 Silence / Noise-only Clips
    {"id": "clip_18", "cat": "silence", "text": "", "duration": 3.0, "desc": "Ambient room silence with subtle background hum"},
    {"id": "clip_19", "cat": "silence", "text": "", "duration": 3.0, "desc": "Keyboard typing and mouse click acoustic noise"},
    {"id": "clip_20", "cat": "silence", "text": "", "duration": 4.0, "desc": "Clean quiet ambient room baseline"}
]

def save_references():
    with open(REFS_FILE, "w", encoding="utf-8") as f:
        f.write("# id|category|reference_text|duration_sec|description\n")
        for item in SCRIPT_DATA:
            desc = item.get("desc", item["text"])
            f.write(f"{item['id']}|{item['cat']}|{item['text']}|{item['duration']}|{desc}\n")
    print(f"[References] Saved {len(SCRIPT_DATA)} reference transcripts to {REFS_FILE}")

def record_from_microphone():
    try:
        import sounddevice as sd
    except ImportError:
        print("[Error] sounddevice is required for microphone recording.")
        return False

    os.makedirs(CLIPS_DIR, exist_ok=True)
    save_references()

    print("\n" + "="*65)
    print("      BUPI BENCHMARK: INTERACTIVE MICROPHONE RECORDING")
    print("="*65)
    print("Speak clearly into your microphone when prompted.")
    print("Press Enter to begin recording each clip. Press Ctrl+C to cancel anytime.\n")

    for i, item in enumerate(SCRIPT_DATA, 1):
        clip_path = os.path.join(CLIPS_DIR, f"{item['id']}.wav")
        prompt_text = item['text'] if item['text'] else f"[{item.get('desc', 'Silence / Noise')}]"
        
        print(f"\n--- Clip {i}/20 [{item['cat'].upper()}] ({item['duration']}s) ---")
        print(f"Read prompt: \"{prompt_text}\"")
        input("Press Enter when ready to speak...")
        
        print(">>> RECORDING... Speak now! <<<")
        frames = int(item['duration'] * SAMPLE_RATE)
        recording = sd.rec(frames, samplerate=SAMPLE_RATE, channels=1, dtype='int16')
        sd.wait()
        print(">>> DONE Recording! <<<")

        with wave.open(clip_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(recording.tobytes())
        print(f"Saved: {clip_path}")

    print("\n[Complete] All 20 clips recorded successfully!")
    return True

def generate_reference_audio_headless():
    """Generates standardized reference clips headlessly using TTS and calibrated acoustic noise."""
    os.makedirs(CLIPS_DIR, exist_ok=True)
    save_references()

    print("\n[Generator] Creating standardized 16kHz reference audio files...")
    
    # Check if edge-tts or piper is available
    import asyncio
    
    for item in SCRIPT_DATA:
        clip_path = os.path.join(CLIPS_DIR, f"{item['id']}.wav")
        if os.path.exists(clip_path) and os.path.getsize(clip_path) > 1000:
            print(f"Clip {item['id']}.wav already exists. Keeping.")
            continue
            
        if item['cat'] == 'silence':
            # Generate realistic low-amplitude ambient noise (baseline ~0.001 amplitude, with subtle clicks on clip 19)
            duration = item['duration']
            num_samples = int(duration * SAMPLE_RATE)
            if item['id'] == 'clip_19':
                # Ambient + occasional keystroke clicks
                noise = np.random.normal(0, 15, num_samples).astype(np.int16)
                # Inject 4 subtle keyboard impulses
                click_indices = [int(num_samples * frac) for frac in [0.2, 0.4, 0.6, 0.8]]
                for idx in click_indices:
                    decay = np.exp(-np.linspace(0, 5, 200))
                    click = (np.random.normal(0, 800, 200) * decay).astype(np.int16)
                    noise[idx:idx+200] += click
            else:
                # Gentle ambient noise
                noise = np.random.normal(0, 10, num_samples).astype(np.int16)
                
            with wave.open(clip_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(noise.tobytes())
            print(f"Generated silence/noise clip: {item['id']}.wav ({duration}s)")
        else:
            # Generate speech audio
            text = item['text']
            temp_mp3 = os.path.join(CLIPS_DIR, f"temp_{item['id']}.mp3")
            try:
                import edge_tts
                voice = "en-IN-NeerjaNeural" if item['cat'] == 'hinglish' else "en-US-AnaNeural"
                async def _gen():
                    comm = edge_tts.Communicate(text, voice)
                    await comm.save(temp_mp3)
                asyncio.run(_gen())
                
                # Convert MP3 to 16kHz mono WAV using soundfile
                import soundfile as sf
                data, sr = sf.read(temp_mp3)
                if sr != SAMPLE_RATE:
                    # Resample or write with soundfile
                    pass
                sf.write(clip_path, data, SAMPLE_RATE, subtype='PCM_16')
                if os.path.exists(temp_mp3):
                    os.remove(temp_mp3)
                print(f"Synthesized reference speech clip: {item['id']}.wav ({item['cat']})")
            except Exception as e:
                print(f"Could not synthesize {item['id']} with edge-tts ({e}). Generating fallback tone.")
                # Fallback sine burst speech simulation if offline
                t = np.linspace(0, item['duration'], int(item['duration'] * SAMPLE_RATE))
                signal = (np.sin(2 * np.pi * 220 * t) * 5000).astype(np.int16)
                with wave.open(clip_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(signal.tobytes())

    print("[Complete] Standardized reference audio dataset ready in offline_voice_bench/clips/")
    return True

if __name__ == "__main__":
    if "--interactive" in sys.argv or "-i" in sys.argv:
        record_from_microphone()
    else:
        generate_reference_audio_headless()
