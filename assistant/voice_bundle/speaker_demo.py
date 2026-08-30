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
    if not ffplay_bin:
        print(f"\n[Playback ERROR] ffplay executable could not be found.")
        print(f"  Audio has been synthesized successfully and saved to: {os.path.abspath(path)}")
        print(f"  Please play this MP3 file manually or add 'ffplay' to your PATH.")
        return False
        
    print(f"[Playback] Playing synthesized speech via ffplay ({ffplay_bin})...")
    
    # Hide command window for clean UX on Windows
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
        proc.wait() # Wait for audio to finish playing
        return True
    except Exception as e:
        print(f"[Playback ERROR] Failed to spawn ffplay player: {e}")
        return False

async def generate_speech(text, voice, path):
    import edge_tts
    print(f"[TTS] Synthesizing speech using voice '{voice}'...")
    print(f"[TTS] Text: \"{text}\"")
    
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(path)
    print(f"[TTS] Audio successfully written to {path} ({os.path.getsize(path)} bytes).")

def main():
    print("=== Standalone Text-to-Speech Speaker ===")
    
    # Check edge_tts
    try:
        import edge_tts
    except ImportError:
        print("[ERROR] edge-tts package is not installed. Run install.bat first.")
        sys.exit(1)
        
    # Check arguments
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = input("Enter the text you want the assistant to speak: ")
        
    if not text.strip():
        print("[ERROR] No text input provided.")
        sys.exit(1)
        
    # Run async TTS generation
    try:
        asyncio.run(generate_speech(text, DEFAULT_VOICE, TEMP_FILE))
        # Play the audio
        play_audio(TEMP_FILE)
    except Exception as e:
        print(f"[ERROR] Failed to run text-to-speech: {e}")
    finally:
        # Clean up temporary audio file
        if os.path.exists(TEMP_FILE):
            try:
                os.remove(TEMP_FILE)
                print("[Cleanup] Removed temporary speech file.")
            except Exception as e:
                print(f"[Cleanup Warning] Could not remove {TEMP_FILE}: {e}")

if __name__ == "__main__":
    main()
