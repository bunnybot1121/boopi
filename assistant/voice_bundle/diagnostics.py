import os
import sys
import subprocess
import shutil

print("=========================================================")
# Print headers with formatting that looks premium in CLI
print("         BUPI VOICE SYSTEMS DIAGNOSTICS TOOL            ")
print("=========================================================\n")

# 1. Python Environment Information
print("--- Python Environment ---")
print(f"Python Executable: {sys.executable}")
print(f"Python Version: {sys.version}")
print(f"Platform: {sys.platform}\n")

# 2. Check Package Imports
required_packages = {
    "PyQt6": "PyQt6",
    "sounddevice": "sounddevice",
    "numpy": "numpy",
    "webrtcvad": "webrtcvad",
    "faster_whisper": "faster_whisper",
    "edge_tts": "edge_tts",
    "requests": "requests",
    "dotenv": "python-dotenv",
}

print("--- Python Packages Check ---")
all_packages_ok = True
for module_name, package_name in required_packages.items():
    try:
        __import__(module_name)
        print(f"  [OK] {package_name} is installed.")
    except ImportError as e:
        print(f"  [MISSING] {package_name} is NOT installed. (Error: {e})")
        all_packages_ok = False
print()

# 3. Check System Tools (ffmpeg & ffplay)
print("--- System Utilities Check ---")
ffmpeg_ok = False
ffplay_ok = False

# Search in PATH
ffmpeg_path = shutil.which("ffmpeg")
ffplay_path = shutil.which("ffplay")

# Search in parent directory (workspace)
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
local_ffmpeg = os.path.join(parent_dir, "ffmpeg.exe")
local_ffplay = os.path.join(parent_dir, "ffplay.exe")

if not ffmpeg_path and os.path.exists(local_ffmpeg):
    ffmpeg_path = local_ffmpeg
if not ffplay_path and os.path.exists(local_ffplay):
    ffplay_path = local_ffplay

if ffmpeg_path:
    print(f"  [OK] ffmpeg found: {ffmpeg_path}")
    ffmpeg_ok = True
else:
    print("  [ERROR] ffmpeg is NOT found in PATH or project root.")

if ffplay_path:
    print(f"  [OK] ffplay found: {ffplay_path}")
    ffplay_ok = True
else:
    print("  [ERROR] ffplay is NOT found in PATH or project root. Audio playback via ffplay will fail.")
print()

# 4. Check Audio Devices
print("--- Audio Devices Check ---")
try:
    import sounddevice as sd
    devices = sd.query_devices()
    default_input = sd.default.device[0]
    default_output = sd.default.device[1]
    
    print(f"Default Input Device ID: {default_input}")
    print(f"Default Output Device ID: {default_output}")
    
    print("\nAvailable Input Devices (Microphones):")
    input_count = 0
    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            is_default = " (DEFAULT)" if i == default_input else ""
            print(f"  [{i}] {dev['name']}{is_default}")
            input_count += 1
            
    if input_count == 0:
         print("  [WARNING] No active input devices found! Check system microphone permissions.")
         
    print("\nAvailable Output Devices (Speakers):")
    output_count = 0
    for i, dev in enumerate(devices):
        if dev['max_output_channels'] > 0:
            is_default = " (DEFAULT)" if i == default_output else ""
            print(f"  [{i}] {dev['name']}{is_default}")
            output_count += 1
            
    if output_count == 0:
         print("  [WARNING] No active output devices found!")
except Exception as e:
    print(f"  [ERROR] Could not query audio devices: {e}")
print()

# 5. Check API Keys (.env)
print("--- API Credentials Check ---")
try:
    from dotenv import load_dotenv
    # Load from parent directory .env
    dotenv_path = os.path.join(parent_dir, ".env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)
        print(f"Loaded credentials from {dotenv_path}")
        
        groq_key = os.environ.get("GROQ_API_KEY")
        if groq_key:
            # Mask the key for display security
            masked = groq_key[:6] + "..." + groq_key[-4:] if len(groq_key) > 10 else "***"
            print(f"  [OK] GROQ_API_KEY found: {masked}")
            print("  Cloud Speech-to-Text (Whisper Large V3) will be active and fast.")
        else:
            print("  [WARNING] GROQ_API_KEY not found in .env. Will fall back to local Whisper (slower, CPU-intensive).")
            
        # Check fallback keys
        additional_keys = []
        for i in range(2, 11):
            if os.environ.get(f"GROQ_API_KEY_{i}"):
                additional_keys.append(f"GROQ_API_KEY_{i}")
        if additional_keys:
            print(f"  [OK] Found {len(additional_keys)} additional Groq fallback keys: {', '.join(additional_keys)}")
            
    else:
        print(f"  [WARNING] No .env file found at {dotenv_path}. Make sure it exists in your project root.")
except Exception as e:
    print(f"  [ERROR] Error checking API keys: {e}")
print()

# Summary
print("--- Diagnostic Summary ---")
issues = []
if not all_packages_ok:
    issues.append("Install missing Python libraries using pip.")
if not ffmpeg_ok or not ffplay_ok:
    issues.append("Ensure ffmpeg/ffplay are added to system PATH or projects folder.")
if not os.path.exists(dotenv_path):
    issues.append("Create a .env file containing your API keys.")

if issues:
    print("Action Required:")
    for issue in issues:
        print(f"  - {issue}")
else:
    print("  [SUCCESS] All checks passed! Voice systems are ready to run.")
print("=========================================================")
