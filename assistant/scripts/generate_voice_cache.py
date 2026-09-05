import os
import sys
import json
import hashlib
import asyncio
import re

# Ensure root directory is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

CACHE_DIR = os.path.join(BASE_DIR, "assets", "voice_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

VOICE = "en-US-AnaNeural"

PHRASES = [
    # Wake & Greetings
    "I'm here.",
    "Yes?",
    "How can I help?",
    "Goodbye! See you next time.",
    "Okay, I'll be here if you need me.",
    "Yay! You finally talked to me again!",
    "Why are you not talking to me?",
    "Shifting to Mode 2. Robotic orchestration enabled.",
    "Shifting to Mode 1. Conversation mode enabled.",

    # Emergency & Safety
    "Emergency stop triggered. Motors halted.",
    "Emergency stop activated. All motors halted.",
    "Obstacle detected ahead. Re-routing path.",
    "Obstacle detected too close ahead. Evasive maneuver executed.",
    "Path is clear. Moving forward.",

    # Autonomous Missions
    "Starting search pattern. Scanning room for human presence.",
    "Scanning surroundings with ultrasonic sensor.",
    "Human detected ahead. Approaching target.",
    "Human located in the room. Mission accomplished.",
    "Starting room patrol and environmental inspection.",
    "Starting autonomous exploration.",
    "Mission stopped.",
    "Mission cancelled.",
    "Mission aborted.",

    # Actuator & Hardware Responses
    "Driving forward.",
    "Driving reverse.",
    "Turning left.",
    "Turning right.",
    "Relay turned on.",
    "Relay turned off.",
    "ESP32 is online and ready.",
    "World state check complete.",
    "No active ESP32 nodes found yet. Waiting for heartbeat."
]

def normalize_key(text: str) -> str:
    clean = text.lower().replace(",", "").replace(";", "").replace(":", "")
    clean = clean.replace("!", ".").strip()
    clean = re.sub(r'\s+', ' ', clean)
    return clean

async def synthesize_all():
    import edge_tts
    index = {}
    print(f"[VoiceCache] Generating 0-ms voice cache for {len(PHRASES)} phrases into {CACHE_DIR}...")
    
    for i, phrase in enumerate(PHRASES):
        key = normalize_key(phrase)
        hash_name = hashlib.md5(key.encode("utf-8")).hexdigest() + ".mp3"
        out_path = os.path.join(CACHE_DIR, hash_name)
        index[key] = hash_name
        
        if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
            print(f"[{i+1}/{len(PHRASES)}] Cached: '{phrase}' -> {hash_name}")
            continue
            
        print(f"[{i+1}/{len(PHRASES)}] Synthesizing: '{phrase}'...")
        try:
            communicate = edge_tts.Communicate(phrase, VOICE, pitch="+10Hz")
            await communicate.save(out_path)
            print(f"  -> Saved {hash_name} ({os.path.getsize(out_path)} bytes)")
        except Exception as e:
            print(f"  -> EdgeTTS failed for '{phrase}': {e}. Trying offline SAPI fallback...")
            try:
                import win32com.client
                speaker_obj = win32com.client.Dispatch("SAPI.SpVoice")
                stream = win32com.client.Dispatch("SAPI.SpFileStream")
                wav_path = os.path.join(CACHE_DIR, hashlib.md5(key.encode("utf-8")).hexdigest() + ".wav")
                stream.Open(wav_path, 3, False)
                speaker_obj.AudioOutputStream = stream
                speaker_obj.Speak(phrase)
                stream.Close()
                index[key] = os.path.basename(wav_path)
                print(f"  -> Saved offline SAPI {wav_path}")
            except Exception as sapi_err:
                print(f"  -> SAPI failed too: {sapi_err}")

    # Write index file
    index_path = os.path.join(CACHE_DIR, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    print(f"[VoiceCache] Finished generating voice cache! Total entries: {len(index)}")

if __name__ == "__main__":
    asyncio.run(synthesize_all())
