import os
import sys
import asyncio
import subprocess
import shutil

# Config
DEFAULT_VOICE = "en-US-AnaNeural"
TEMP_FILE = "temp_demo_speech.mp3"

def find_ffplay():
    # Check PATH
    ffplay_path = shutil.which("ffplay")
    if ffplay_path:
        return ffplay_path
        
    # Check parent workspace directory
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_ffplay = os.path.join(parent_dir, "ffplay.exe")
    if os.path.exists(local_ffplay):
        return local_ffplay
        
    return None

def play_audio(path):
    ffplay_bin = find_ffplay()
    if ffplay_bin:
        print(f"[Playback] Playing synthesized speech via ffplay ({ffplay_bin})...")
        startupinfo = None
        creationflags = 0
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            proc = subprocess.Popen(
                [ffplay_bin, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            proc.wait()
            return True
        except Exception as e:
            print(f"[Playback ERROR] Failed to spawn ffplay player: {e}")

    # Fallback: Local ffmpeg + native Windows winsound
    try:
        import winsound
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ffmpeg_bin = os.path.join(parent_dir, "ffmpeg.exe")
        if os.path.exists(ffmpeg_bin):
            print("[Playback] Playing audio via native Windows audio subsystem...")
            temp_wav = path + ".wav"
            subprocess.run([ffmpeg_bin, "-y", "-i", path, temp_wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(temp_wav):
                winsound.PlaySound(temp_wav, winsound.SND_FILENAME)
                try: os.remove(temp_wav)
                except Exception: pass
                return True
    except Exception as fallback_err:
        print(f"[Playback Warning] Native audio playback fallback failed: {fallback_err}")

    print(f"\n[Playback Notice] Audio synthesized and saved to: {os.path.abspath(path)}")
    return False

async def generate_speech(text, voice, path):
    try:
        import edge_tts
        print(f"[TTS] Synthesizing speech using Boopi voice '{voice}'...")
        communicate = edge_tts.Communicate(text, voice, pitch="+10Hz", rate="+0%")
        await communicate.save(path)
        print(f"[TTS] Audio successfully written to {path} ({os.path.getsize(path)} bytes).")
        return path
    except Exception as e:
        print(f"[TTS] Edge-TTS error ({e}), attempting offline fallback...")

    # Offline Piper fallback if network is down
    try:
        import piper
        import wave
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        piper_dir = os.path.join(parent_dir, "assets", "models", "piper")
        model_path = os.path.join(piper_dir, "en_US-amy-medium.onnx")
        config_path = os.path.join(piper_dir, "en_US-amy-medium.onnx.json")
        if os.path.exists(model_path) and os.path.exists(config_path):
            print(f"[TTS] Synthesizing speech using offline Piper fallback...")
            piper_voice = piper.PiperVoice.load(model_path, config_path=config_path)
            wav_path = path[:-4] + ".wav" if path.endswith(".mp3") else path
            with wave.open(wav_path, "wb") as wf:
                piper_voice.synthesize_wav(text, wf)
            return wav_path
    except Exception as fallback_err:
        print(f"[TTS] Offline fallback error: {fallback_err}")
    return path

def main():
    print("=== Standalone Text-to-Speech Speaker ===")
    
    # Check arguments
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = input("Enter the text you want the assistant to speak: ")
        
    if not text.strip():
        print("[ERROR] No text input provided.")
        sys.exit(1)
        
    actual_path = None
    # Run TTS generation
    try:
        actual_path = asyncio.run(generate_speech(text, DEFAULT_VOICE, TEMP_FILE))
        # Play the audio
        if actual_path and os.path.exists(actual_path):
            play_audio(actual_path)
    except Exception as e:
        print(f"[ERROR] Failed to run text-to-speech: {e}")
    finally:
        # Clean up temporary audio file
        for f in [TEMP_FILE, actual_path]:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                    print(f"[Cleanup] Removed temporary speech file {f}.")
                except Exception as e:
                    print(f"[Cleanup Warning] Could not remove {f}: {e}")

if __name__ == "__main__":
    main()
