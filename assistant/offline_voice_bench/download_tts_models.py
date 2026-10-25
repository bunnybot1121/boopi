"""
Downloader for offline TTS models: Kokoro-82M and Piper voices.
All files are under 350 MB each (well below the 2 GB threshold).
"""

import os
import sys
import urllib.request
import time

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BENCH_DIR, "models")
KOKORO_DIR = os.path.join(MODELS_DIR, "kokoro")
PIPER_DIR = os.path.join(MODELS_DIR, "piper")

os.makedirs(KOKORO_DIR, exist_ok=True)
os.makedirs(PIPER_DIR, exist_ok=True)

DOWNLOADS = [
    # Kokoro ONNX model and voices bundle
    {
        "name": "Kokoro v1.0 ONNX model",
        "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.onnx",
        "dest": os.path.join(KOKORO_DIR, "kokoro-v1.0.onnx"),
        "min_size": 100 * 1024 * 1024
    },
    {
        "name": "Kokoro v1.0 Voices bundle",
        "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin",
        "dest": os.path.join(KOKORO_DIR, "voices-v1.0.bin"),
        "min_size": 10 * 1024 * 1024
    },
    # Piper English High Voice (Ryan High)
    {
        "name": "Piper en_US-ryan-high ONNX",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx",
        "dest": os.path.join(PIPER_DIR, "en_US-ryan-high.onnx"),
        "min_size": 50 * 1024 * 1024
    },
    {
        "name": "Piper en_US-ryan-high Config JSON",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json",
        "dest": os.path.join(PIPER_DIR, "en_US-ryan-high.onnx.json"),
        "min_size": 1000
    },
    # Piper Hindi Medium Voice (Priyamvada)
    {
        "name": "Piper hi_IN-priyamvada-medium ONNX",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/hi/hi_IN/priyamvada/medium/hi_IN-priyamvada-medium.onnx",
        "dest": os.path.join(PIPER_DIR, "hi_IN-priyamvada-medium.onnx"),
        "min_size": 30 * 1024 * 1024
    },
    {
        "name": "Piper hi_IN-priyamvada-medium Config JSON",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/hi/hi_IN/priyamvada/medium/hi_IN-priyamvada-medium.onnx.json",
        "dest": os.path.join(PIPER_DIR, "hi_IN-priyamvada-medium.onnx.json"),
        "min_size": 1000
    }
]

def download_file(item):
    dest = item["dest"]
    if os.path.exists(dest) and os.path.getsize(dest) >= item["min_size"]:
        print(f"[Exists] {item['name']} already present ({os.path.getsize(dest)/(1024*1024):.1f} MB)")
        return True

    print(f"[Downloading] {item['name']} from {item['url']}...")
    try:
        start = time.time()
        req = urllib.request.Request(item["url"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
            total_bytes = 0
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                total_bytes += len(chunk)
        elapsed = time.time() - start
        size_mb = total_bytes / (1024 * 1024)
        print(f"[Done] {item['name']} downloaded: {size_mb:.1f} MB in {elapsed:.1f}s ({size_mb/max(elapsed, 0.1):.1f} MB/s)")
        return True
    except Exception as e:
        print(f"[Failed] {item['name']} download error: {e}")
        if os.path.exists(dest):
            try: os.remove(dest)
            except: pass
        return False

def download_all():
    print("=" * 65)
    print("      BUPI BENCHMARK: DOWNLOADING TTS MODELS (KOKORO + PIPER)")
    print("=" * 65)
    for item in DOWNLOADS:
        download_file(item)
    print("\n[Complete] TTS model assets downloaded and verified!")

if __name__ == "__main__":
    download_all()
