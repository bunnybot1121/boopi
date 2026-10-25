"""
BUPI Offline Voice Stack Benchmark - End-to-End Pipeline Latency
Measures the complete conversational turn:
Audio Input (WAV) -> STT (CPU) -> Local LLM (GPU) -> TTS First Audio (CPU)
Measures TTFA (Time to First Audio) with 2 warm-up runs and 5 timed runs (median and p95).
"""

import os
import sys
import time
import json
import urllib.request
import numpy as np

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
if BENCH_DIR not in sys.path:
    sys.path.insert(0, BENCH_DIR)

from bench_utils import get_current_vram_mb, stats

OLLAMA_GEN_URL = "http://127.0.0.1:11434/api/generate"

def stream_llm_first_sentence(model, prompt):
    """Streams from Ollama until the first complete sentence is yielded."""
    payload = {
        "model": model,
        "prompt": prompt,
        "system": "You are Boopi, a helpful cute desktop robot assistant. Answer directly in one concise sentence.",
        "stream": True,
        "options": {"temperature": 0.0, "num_predict": 40}
    }
    req = urllib.request.Request(OLLAMA_GEN_URL, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    
    first_token_time = None
    accumulated_text = ""
    t0 = time.perf_counter()
    
    with urllib.request.urlopen(req, timeout=30) as resp:
        for line in resp:
            if not line:
                continue
            chunk = json.loads(line.decode("utf-8"))
            tok = chunk.get("response", "")
            if tok and first_token_time is None:
                first_token_time = time.perf_counter()
            accumulated_text += tok
            # Check for sentence end
            if any(p in accumulated_text for p in [".", "!", "?"]) and len(accumulated_text.split()) >= 3:
                break
            if chunk.get("done", False):
                break
                
    t1 = time.perf_counter()
    return accumulated_text.strip(), (first_token_time - t0 if first_token_time else t1 - t0), (t1 - t0)

def run_e2e_benchmark(combos=None):
    """
    Evaluates top candidate combinations:
    Combo 1: Faster-Whisper base.en + Llama-3.2:3b + Kokoro-82M
    Combo 2: Parakeet TDT 0.6B + Llama-3.2:3b + Piper Ryan High
    """
    print("=" * 70)
    print("      BUPI OFFLINE VOICE BENCHMARK: END-TO-END PIPELINE LATENCY")
    print("=" * 70)

    test_clip = os.path.join(BENCH_DIR, "clips", "clip_01.wav")
    if not os.path.exists(test_clip):
        print(f"[Error] Test clip {test_clip} not found. Please run record_clips.py first.")
        return []

    # Initialize STT engines
    print("\n[Init] Pre-loading STT & TTS runners...")
    from faster_whisper import WhisperModel
    whisper_base = WhisperModel("base.en", device="cpu", compute_type="int8", cpu_threads=8)
    
    import onnx_asr
    parakeet = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization="int8", providers=["CPUExecutionProvider"])
    
    from kokoro_onnx import Kokoro
    kokoro = Kokoro(
        os.path.join(BENCH_DIR, "models", "kokoro", "kokoro-v1.0.onnx"),
        os.path.join(BENCH_DIR, "models", "kokoro", "voices-v1.0.bin")
    )
    
    import piper
    piper_ryan = piper.PiperVoice.load(
        os.path.join(BENCH_DIR, "models", "piper", "en_US-ryan-high.onnx"),
        config_path=os.path.join(BENCH_DIR, "models", "piper", "en_US-ryan-high.onnx.json")
    )

    if combos is None:
        combos = [
            {
                "name": "Combo A (Ultra-Fast Lightweight): Faster-Whisper base.en + Llama-3.2:3b + Kokoro-82M",
                "stt_fn": lambda wav: " ".join(s.text.strip() for s, _ in [whisper_base.transcribe(wav, beam_size=1, temperature=0.0)][0]),
                "llm_model": "llama3.2:3b",
                "tts_fn": lambda txt: kokoro.create(txt, voice="af_bella", speed=1.0, lang="en-us")
            },
            {
                "name": "Combo B (Enterprise Transducer): Parakeet TDT 0.6B + Llama-3.2:3b + Piper Ryan High",
                "stt_fn": lambda wav: parakeet.recognize(wav),
                "llm_model": "llama3.2:3b",
                "tts_fn": lambda txt: piper_ryan.synthesize(txt)
            }
        ]

    results = []

    for combo in combos:
        cname = combo["name"]
        print(f"\n>>> Benchmarking Combo: {cname} <<<")
        stt_fn = combo["stt_fn"]
        llm_model = combo["llm_model"]
        tts_fn = combo["tts_fn"]

        # 2 Warm-up runs
        for _ in range(2):
            try:
                t_stt = stt_fn(test_clip)
                s_text, _, _ = stream_llm_first_sentence(llm_model, t_stt)
                tts_fn(s_text)
            except Exception:
                pass

        total_latencies = []
        stt_latencies = []
        llm_ttft_latencies = []
        tts_first_chunk_latencies = []

        for run_idx in range(5):
            t_start = time.perf_counter()
            
            # Step 1: STT
            t0 = time.perf_counter()
            user_transcript = stt_fn(test_clip)
            t_stt_done = time.perf_counter()
            stt_dur = t_stt_done - t0
            
            # Step 2: LLM (stream to first sentence)
            first_sentence, llm_ttft, llm_dur = stream_llm_first_sentence(llm_model, user_transcript)
            t_llm_done = time.perf_counter()
            
            # Step 3: TTS first chunk synthesis
            t_tts0 = time.perf_counter()
            tts_fn(first_sentence)
            t_tts_done = time.perf_counter()
            tts_dur = t_tts_done - t_tts0
            
            t_total = t_tts_done - t_start
            
            total_latencies.append(t_total)
            stt_latencies.append(stt_dur)
            llm_ttft_latencies.append(llm_ttft)
            tts_first_chunk_latencies.append(tts_dur)

        st_tot = stats(total_latencies)
        st_stt = stats(stt_latencies)
        st_llm = stats(llm_ttft_latencies)
        st_tts = stats(tts_first_chunk_latencies)

        print(f"Result for {cname}:")
        print(f"  TOTAL Pipeline Time-To-First-Audio: {st_tot['median']:.3f}s (p95: {st_tot['p95']:.3f}s)")
        print(f"  Breakdown (Median): STT = {st_stt['median']:.3f}s | LLM TTFT = {st_llm['median']:.3f}s | TTS First Audio = {st_tts['median']:.3f}s")
        print(f"  Last user transcript: \"{user_transcript}\"")
        print(f"  Last robot spoken reply: \"{first_sentence}\"")

        results.append({
            "combo_name": cname,
            "stt_median_sec": st_stt["median"],
            "llm_ttft_median_sec": st_llm["median"],
            "tts_first_audio_median_sec": st_tts["median"],
            "pipeline_total_median_sec": st_tot["median"],
            "pipeline_total_p95_sec": st_tot["p95"],
            "sample_stt": user_transcript,
            "sample_response": first_sentence
        })

    e2e_json_path = os.path.join(BENCH_DIR, "e2e_results.json")
    with open(e2e_json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n[Complete] End-to-end benchmark complete! Saved to {e2e_json_path}")
    return results

if __name__ == "__main__":
    run_e2e_benchmark()
