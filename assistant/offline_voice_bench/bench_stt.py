"""
BUPI Offline Voice Stack Benchmark - STT Engine Benchmarking
Measures RTF, Latency, WER (English & Hinglish), Silence Hallucinations, Peak RAM, and CPU % across:
- NVIDIA Parakeet TDT 0.6B v3 (ONNX INT8 on CPU)
- Faster-Whisper INT8 (base.en, small, medium, distil-large-v3, large-v3-turbo) across cpu_threads = 6, 8, 14
- Udgam Labs Shruti (55M Hindi/English/Hinglish via needle)
- Oriserve Whisper-Hindi2Hinglish-Swift (72.6M parameters)
"""

import os
import sys
import time
import json
import wave
import numpy as np
import soundfile as sf

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
if BENCH_DIR not in sys.path:
    sys.path.insert(0, BENCH_DIR)

from bench_utils import ResourceMonitor, calculate_wer, stats

CLIPS_DIR = os.path.join(BENCH_DIR, "clips")
REFS_FILE = os.path.join(BENCH_DIR, "references.txt")
MODELS_DIR = os.path.join(BENCH_DIR, "models")

def load_references():
    refs = []
    with open(REFS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            clip_id = parts[0]
            cat = parts[1]
            text = parts[2]
            dur = float(parts[3])
            desc = parts[4] if len(parts) > 4 else text
            wav_path = os.path.join(CLIPS_DIR, f"{clip_id}.wav")
            refs.append({
                "id": clip_id,
                "cat": cat,
                "text": text,
                "duration": dur,
                "desc": desc,
                "path": wav_path
            })
    return refs

class FasterWhisperRunner:
    def __init__(self, model_size="base.en", cpu_threads=8):
        from faster_whisper import WhisperModel
        self.model_size = model_size
        self.cpu_threads = cpu_threads
        self.model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            cpu_threads=cpu_threads
        )

    def transcribe(self, wav_path):
        segments, _ = self.model.transcribe(
            wav_path,
            beam_size=1,
            temperature=0.0,
            vad_filter=False,
            condition_on_previous_text=False
        )
        return " ".join(s.text.strip() for s in segments).strip()

class ParakeetRunner:
    def __init__(self):
        import onnx_asr
        self.model = onnx_asr.load_model(
            "nemo-parakeet-tdt-0.6b-v3",
            quantization="int8",
            providers=["CPUExecutionProvider"]
        )

    def transcribe(self, wav_path):
        res = self.model.recognize(wav_path)
        if isinstance(res, dict):
            return res.get("text", "")
        return str(res).strip()

class ShrutiRunner:
    def __init__(self):
        from needle import Whistle
        cact_path = os.path.join(MODELS_DIR, "shruti", "shruti.cact")
        self.model = Whistle(cact_path)

    def transcribe(self, wav_path):
        res = self.model.transcribe(wav_path)
        if isinstance(res, dict):
            return res.get("text", "").strip()
        return str(res).strip()

class OriserveRunner:
    def __init__(self):
        from transformers import pipeline
        self.pipe = pipeline(
            "automatic-speech-recognition",
            model="Oriserve/Whisper-Hindi2Hinglish-Swift",
            device="cpu"
        )

    def transcribe(self, wav_path):
        res = self.pipe(wav_path)
        if isinstance(res, dict):
            return res.get("text", "").strip()
        return str(res).strip()

def evaluate_stt_model(name, runner_factory, refs, extra_metadata=None):
    print(f"\n=======================================================")
    print(f"  BENCHMARKING STT: {name}")
    print(f"=======================================================")
    
    t_load0 = time.perf_counter()
    try:
        runner = runner_factory()
    except Exception as e:
        print(f"[SKIPPED] Model {name} could not be loaded: {e}")
        return {
            "model": name,
            "status": "SKIPPED",
            "error": str(e)
        }
    t_load1 = time.perf_counter()
    load_time = round(t_load1 - t_load0, 2)
    print(f"Loaded {name} in {load_time}s")

    # 2 Warm-up runs on clip_01
    warmup_clip = refs[0]["path"]
    for _ in range(2):
        try:
            runner.transcribe(warmup_clip)
        except Exception:
            pass

    mon = ResourceMonitor()
    mon.start()

    clip_results = []
    eng_wers = []
    hinglish_wers = []
    silence_words_invented = 0
    all_latencies = []
    all_rtfs = []

    for item in refs:
        wav_path = item["path"]
        ground_truth = item["text"]
        cat = item["cat"]
        dur = item["duration"]

        if not os.path.exists(wav_path):
            continue

        # 5 timed runs per clip
        runs_time = []
        hyp_text = ""
        for r in range(5):
            mon.sample()
            t0 = time.perf_counter()
            hyp_text = runner.transcribe(wav_path)
            t1 = time.perf_counter()
            runs_time.append(t1 - t0)
            mon.sample()

        st = stats(runs_time)
        med_lat = st["median"]
        p95_lat = st["p95"]
        rtf = med_lat / max(dur, 0.01)

        all_latencies.append(med_lat)
        all_rtfs.append(rtf)

        wer = calculate_wer(ground_truth, hyp_text)
        if cat in ["english", "hardware"]:
            eng_wers.append(wer)
        elif cat == "hinglish":
            hinglish_wers.append(wer)
        elif cat == "silence":
            clean_hyp = hyp_text.strip()
            if clean_hyp:
                silence_words_invented += len(clean_hyp.split())

        clip_results.append({
            "clip_id": item["id"],
            "cat": cat,
            "duration": dur,
            "ground_truth": ground_truth,
            "transcription": hyp_text,
            "latency_median": med_lat,
            "latency_p95": p95_lat,
            "rtf": round(rtf, 3),
            "wer": round(wer, 3)
        })

    res_usage = mon.stop()

    avg_eng_wer = round(float(np.mean(eng_wers)), 3) if eng_wers else 0.0
    avg_hing_wer = round(float(np.mean(hinglish_wers)), 3) if hinglish_wers else 0.0
    lat_summary = stats(all_latencies)
    rtf_summary = stats(all_rtfs)

    print(f"Summary for {name}:")
    print(f"  RTF: {rtf_summary['median']:.3f}x (p95: {rtf_summary['p95']:.3f}x)")
    print(f"  Latency: {lat_summary['median']:.3f}s (p95: {lat_summary['p95']:.3f}s)")
    print(f"  English/Hardware WER: {avg_eng_wer * 100:.1f}%")
    print(f"  Hinglish WER: {avg_hing_wer * 100:.1f}%")
    print(f"  Silence Hallucinations: {silence_words_invented} invented words")
    print(f"  RAM: {res_usage['peak_ram_mb']} MB | CPU: {res_usage['avg_cpu_percent']}%")

    out_record = {
        "model": name,
        "status": "COMPLETED",
        "load_time_sec": load_time,
        "rtf_median": rtf_summary["median"],
        "rtf_p95": rtf_summary["p95"],
        "latency_median_sec": lat_summary["median"],
        "latency_p95_sec": lat_summary["p95"],
        "wer_english": avg_eng_wer,
        "wer_hinglish": avg_hing_wer,
        "silence_hallucinations": silence_words_invented,
        "peak_ram_mb": res_usage["peak_ram_mb"],
        "avg_cpu_percent": res_usage["avg_cpu_percent"],
        "clips_evaluated": len(clip_results)
    }
    if extra_metadata:
        out_record.update(extra_metadata)
    return out_record

def run_stt_benchmark():
    refs = load_references()
    print(f"Loaded {len(refs)} reference clips for STT evaluation.")

    all_results = []

    # 1. Faster-Whisper Thread Tuning on CPU (cpu_threads = 6, 8, 14) using base.en
    print("\n--- FASTER-WHISPER THREAD TUNING (cpu_threads = 6, 8, 14) ---")
    for threads in [6, 8, 14]:
        name = f"Faster-Whisper base.en (threads={threads})"
        res = evaluate_stt_model(
            name,
            lambda t=threads: FasterWhisperRunner("base.en", cpu_threads=t),
            refs,
            {"family": "Faster-Whisper", "model_size": "base.en", "threads": threads, "quant": "int8"}
        )
        all_results.append(res)

    # Pick best thread setting from base.en for other sizes
    completed_threads = [r for r in all_results if r.get("threads") and r.get("status") == "COMPLETED"]
    best_thread_setting = 8
    if completed_threads:
        best_r = min(completed_threads, key=lambda x: x["rtf_median"])
        best_thread_setting = best_r["threads"]
        print(f"\n>>> Best CPU Thread setting found: {best_thread_setting} threads (RTF: {best_r['rtf_median']:.3f}x) <<<")

    # 2. Faster-Whisper Model Sizes (int8 on CPU) with best thread setting
    for sz in ["small", "medium", "distil-large-v3", "large-v3-turbo"]:
        name = f"Faster-Whisper {sz} (threads={best_thread_setting})"
        res = evaluate_stt_model(
            name,
            lambda s=sz, t=best_thread_setting: FasterWhisperRunner(s, cpu_threads=t),
            refs,
            {"family": "Faster-Whisper", "model_size": sz, "threads": best_thread_setting, "quant": "int8"}
        )
        all_results.append(res)

    # 3. NVIDIA Parakeet TDT 0.6B v3 (ONNX INT8 on CPU)
    res_parakeet = evaluate_stt_model(
        "NVIDIA Parakeet TDT 0.6B v3 (ONNX INT8)",
        lambda: ParakeetRunner(),
        refs,
        {"family": "Parakeet", "model_size": "0.6B", "quant": "int8"}
    )
    all_results.append(res_parakeet)

    # 4. Udgam Labs Shruti (55M Hindi/English/Hinglish)
    res_shruti = evaluate_stt_model(
        "Udgam Labs Shruti (55M Hindi/English/Hinglish)",
        lambda: ShrutiRunner(),
        refs,
        {"family": "Shruti", "model_size": "55M", "quant": "4-bit cact"}
    )
    all_results.append(res_shruti)

    # 5. Oriserve Whisper-Hindi2Hinglish-Swift (72.6M)
    res_oriserve = evaluate_stt_model(
        "Oriserve Whisper-Hindi2Hinglish-Swift (72.6M)",
        lambda: OriserveRunner(),
        refs,
        {"family": "Whisper Fine-tune", "model_size": "72.6M", "quant": "FP32 PyTorch"}
    )
    all_results.append(res_oriserve)

    # Save to JSON
    stt_json_path = os.path.join(BENCH_DIR, "stt_results.json")
    with open(stt_json_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n[Complete] STT benchmark finished! Results saved to {stt_json_path}")
    return all_results

if __name__ == "__main__":
    run_stt_benchmark()
