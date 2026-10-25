"""
BUPI Offline Voice Stack Benchmark - TTS Engine Benchmarking
Measures TTFA, RTF, CPU %, and Peak RAM across:
- Kokoro-82M (ONNX CPU)
- Piper (Amy Medium, Ryan High, Priyamvada Hindi)
- SAPI5 (Offline Baseline)
- Edge-TTS (Cloud Baseline, labelled)
"""

import os
import sys
import time
import wave
import json
import asyncio
import numpy as np
import soundfile as sf

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
if BENCH_DIR not in sys.path:
    sys.path.insert(0, BENCH_DIR)

from test_prompts import TTS_PROMPTS
from bench_utils import ResourceMonitor, stats

MODELS_DIR = os.path.join(BENCH_DIR, "models")
AUDIO_OUT_DIR = os.path.join(BENCH_DIR, "audio_out")
os.makedirs(AUDIO_OUT_DIR, exist_ok=True)

class KokoroRunner:
    def __init__(self, voice="af_bella"):
        from kokoro_onnx import Kokoro
        onnx_path = os.path.join(MODELS_DIR, "kokoro", "kokoro-v1.0.onnx")
        voices_path = os.path.join(MODELS_DIR, "kokoro", "voices-v1.0.bin")
        self.engine = Kokoro(onnx_path, voices_path)
        self.voice = voice

    def synthesize(self, text):
        samples, sr = self.engine.create(text, voice=self.voice, speed=1.0, lang="en-us")
        duration = len(samples) / sr
        return samples, sr, duration

class PiperRunner:
    def __init__(self, model_filename):
        import piper
        model_path = os.path.join(MODELS_DIR, "piper", model_filename)
        if not os.path.exists(model_path):
            # Fallback to project root piper dir if present
            root_piper = os.path.join(os.path.dirname(BENCH_DIR), "assets", "models", "piper", model_filename)
            if os.path.exists(root_piper):
                model_path = root_piper
        config_path = model_path + ".json"
        self.voice = piper.PiperVoice.load(model_path, config_path=config_path)

    def synthesize(self, text, out_wav_path):
        with wave.open(out_wav_path, "wb") as wf:
            self.voice.synthesize_wav(text, wf)
        data, sr = sf.read(out_wav_path)
        duration = len(data) / sr
        return data, sr, duration

class SAPI5Runner:
    def __init__(self):
        import win32com.client
        self.speaker = win32com.client.Dispatch("SAPI.SpVoice")
        try:
            for v in self.speaker.GetVoices():
                desc = v.GetDescription().lower()
                if "zira" in desc or "female" in desc:
                    self.speaker.Voice = v
                    break
        except Exception:
            pass

    def synthesize(self, text, out_wav_path):
        import win32com.client
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(out_wav_path, 3, False)
        self.speaker.AudioOutputStream = stream
        self.speaker.Speak(text)
        stream.Close()
        data, sr = sf.read(out_wav_path)
        duration = len(data) / sr
        return data, sr, duration

class EdgeTTSRunner:
    def __init__(self, voice="en-US-AnaNeural"):
        self.voice = voice

    def synthesize(self, text, out_wav_path):
        import edge_tts
        temp_mp3 = out_wav_path.replace(".wav", ".mp3")
        async def _gen():
            comm = edge_tts.Communicate(text, self.voice)
            await comm.save(temp_mp3)
        asyncio.run(_gen())
        data, sr = sf.read(temp_mp3)
        sf.write(out_wav_path, data, sr)
        if os.path.exists(temp_mp3):
            os.remove(temp_mp3)
        duration = len(data) / sr
        return data, sr, duration

def run_tts_benchmark():
    print("=" * 70)
    print("            BUPI OFFLINE VOICE BENCHMARK: TTS ENGINES")
    print("=" * 70)

    engines = {}
    
    # 1. Kokoro-82M
    try:
        print("[Init] Loading Kokoro-82M (ONNX CPU)...")
        engines["Kokoro-82M (af_bella)"] = {
            "type": "kokoro",
            "runner": KokoroRunner(voice="af_bella"),
            "offline": True,
            "quant": "FP32 ONNX"
        }
    except Exception as e:
        print(f"[Warning] Kokoro init failed: {e}")

    # 2. Piper Ryan High
    try:
        print("[Init] Loading Piper (en_US-ryan-high)...")
        engines["Piper (Ryan High)"] = {
            "type": "piper",
            "runner": PiperRunner("en_US-ryan-high.onnx"),
            "offline": True,
            "quant": "ONNX (high)"
        }
    except Exception as e:
        print(f"[Warning] Piper Ryan High init failed: {e}")

    # 3. Piper Amy Medium
    try:
        print("[Init] Loading Piper (en_US-amy-medium)...")
        engines["Piper (Amy Medium)"] = {
            "type": "piper",
            "runner": PiperRunner("en_US-amy-medium.onnx"),
            "offline": True,
            "quant": "ONNX (medium)"
        }
    except Exception as e:
        print(f"[Warning] Piper Amy Medium init failed: {e}")

    # 4. Piper Hindi Priyamvada
    try:
        print("[Init] Loading Piper Hindi (hi_IN-priyamvada-medium)...")
        engines["Piper (Priyamvada Hindi)"] = {
            "type": "piper",
            "runner": PiperRunner("hi_IN-priyamvada-medium.onnx"),
            "offline": True,
            "quant": "ONNX (medium)"
        }
    except Exception as e:
        print(f"[Warning] Piper Hindi init failed: {e}")

    # 5. SAPI5 (Offline Baseline)
    try:
        print("[Init] Loading Windows SAPI5 (Offline Baseline)...")
        engines["SAPI5 (Windows Offline Baseline)"] = {
            "type": "sapi",
            "runner": SAPI5Runner(),
            "offline": True,
            "quant": "Native SAPI5"
        }
    except Exception as e:
        print(f"[Warning] SAPI5 init failed: {e}")

    # 6. Edge-TTS (Cloud Baseline, labelled)
    try:
        print("[Init] Preparing Edge-TTS (Cloud Baseline - Online)...")
        engines["Edge-TTS (Online Baseline)"] = {
            "type": "edge_tts",
            "runner": EdgeTTSRunner("en-US-AnaNeural"),
            "offline": False,
            "quant": "Cloud Neural"
        }
    except Exception as e:
        print(f"[Warning] Edge-TTS init failed: {e}")

    results = []
    mon = ResourceMonitor()

    for engine_name, cfg in engines.items():
        runner = cfg["runner"]
        eng_type = cfg["type"]
        print(f"\n>>> Benchmarking Engine: {engine_name} ({'100% Offline' if cfg['offline'] else 'Cloud Online'}) <<<")

        for size_key, text in TTS_PROMPTS.items():
            out_file = os.path.join(AUDIO_OUT_DIR, f"{engine_name.replace(' ', '_').replace('(', '').replace(')', '').replace('/', '_')}_{size_key}.wav")
            
            # 2 Warm-up runs
            for _ in range(2):
                try:
                    if eng_type == "kokoro":
                        samples, sr, _ = runner.synthesize(text[:25])
                    else:
                        runner.synthesize(text[:25], out_file)
                except Exception:
                    pass

            # 5 Timed runs
            latencies = []
            rtfs = []
            durations = []
            
            mon.start()
            for run_idx in range(5):
                mon.sample()
                t0 = time.perf_counter()
                
                if eng_type == "kokoro":
                    samples, sr, audio_dur = runner.synthesize(text)
                    sf.write(out_file, samples, sr)
                else:
                    samples, sr, audio_dur = runner.synthesize(text, out_file)
                    
                t1 = time.perf_counter()
                elapsed = t1 - t0
                rtf = elapsed / max(audio_dur, 0.01)
                
                latencies.append(elapsed)
                rtfs.append(rtf)
                durations.append(audio_dur)
                mon.sample()

            res_usage = mon.stop()
            lat_stats = stats(latencies)
            rtf_stats = stats(rtfs)
            avg_audio_dur = round(float(np.mean(durations)), 2)

            print(f"  [{size_key.upper()} ~{len(text.split())} words] "
                  f"Latency: {lat_stats['median']:.3f}s (p95: {lat_stats['p95']:.3f}s) | "
                  f"Audio: {avg_audio_dur}s | RTF: {rtf_stats['median']:.3f}x | "
                  f"RAM: {res_usage['peak_ram_mb']}MB | CPU: {res_usage['avg_cpu_percent']}%")

            results.append({
                "category": "TTS",
                "engine": engine_name,
                "offline": cfg["offline"],
                "quantization": cfg["quant"],
                "prompt_size": size_key,
                "word_count": len(text.split()),
                "audio_duration_sec": avg_audio_dur,
                "latency_median_sec": lat_stats["median"],
                "latency_p95_sec": lat_stats["p95"],
                "rtf_median": rtf_stats["median"],
                "rtf_p95": rtf_stats["p95"],
                "peak_ram_mb": res_usage["peak_ram_mb"],
                "avg_cpu_percent": res_usage["avg_cpu_percent"],
                "audio_file": os.path.basename(out_file)
            })

    # Save TTS results json
    tts_json_path = os.path.join(BENCH_DIR, "tts_results.json")
    with open(tts_json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n[Complete] TTS benchmark finished! Saved {len(results)} metrics to {tts_json_path}")
    return results

if __name__ == "__main__":
    run_tts_benchmark()
