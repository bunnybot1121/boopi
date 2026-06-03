import sounddevice as sd
import numpy as np

print("=== BUPI MICROPHONE DIAGNOSTICS ===")

devices = sd.query_devices()
default_in = sd.default.device[0]

print(f"\nDefault Input Device ID: {default_in}")

print("\nAvailable Input Devices:")
for i, dev in enumerate(devices):
    if dev['max_input_channels'] > 0:
        is_default = " (DEFAULT)" if i == default_in else ""
        print(f"[{i}] {dev['name']}{is_default}")

print("\nTesting Default Microphone for 2 seconds...")
try:
    with sd.InputStream(samplerate=16000, channels=1, dtype='int16') as stream:
        frames = []
        for _ in range(20): # 2 seconds (100ms blocks)
            data, _ = stream.read(1600)
            rms = np.sqrt(np.mean(np.square(data, dtype=np.float32)))
            frames.append(rms)
        
        avg_rms = sum(frames) / len(frames)
        max_rms = max(frames)
        print(f"Average Volume (RMS): {avg_rms:.2f}")
        print(f"Peak Volume (RMS): {max_rms:.2f}")
        
        if max_rms < 5:
            print("\nWARNING: Your microphone is completely silent! Python is not receiving audio.")
            print("Fix 1: Check Windows Settings -> Privacy -> Microphone -> 'Allow desktop apps to access your microphone'.")
            print("Fix 2: Make sure your headset is selected as the Default Recording Device in Windows Sound Control Panel.")
        else:
            print("\nSUCCESS: Python is receiving audio properly! Voice-to-text should work.")
except Exception as e:
    print(f"\nERROR testing microphone: {e}")
