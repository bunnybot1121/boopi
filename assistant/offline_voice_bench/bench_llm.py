"""
BUPI Offline Voice Stack Benchmark - Local LLM Benchmarking (Ollama on GPU)
Measures TTFT, tokens/sec, VRAM footprint, intent routing accuracy, and JSON tool-call validity across:
- llama3.2:3b (local baseline)
- llama3.1:8b (local baseline)
- phi4-mini
- qwen3:4b-instruct
- qwen3:8b
"""

import os
import sys
import time
import json
import urllib.request
import urllib.error
import re
import numpy as np

BENCH_DIR = os.path.dirname(os.path.abspath(__file__))
if BENCH_DIR not in sys.path:
    sys.path.insert(0, BENCH_DIR)

from test_prompts import INTENT_PROMPTS, JSON_TEST_PROMPTS
from bench_utils import get_current_vram_mb, stats

OLLAMA_GEN_URL = "http://127.0.0.1:11434/api/generate"

def query_ollama_streaming(model, prompt, system_prompt="You are a fast voice assistant. Answer directly and concisely with no thinking tags."):
    """Streams response from Ollama API to measure TTFT and generation speed."""
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system_prompt,
        "stream": True,
        "options": {
            "temperature": 0.0,
            "top_p": 0.9,
            "num_predict": 128
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(OLLAMA_GEN_URL, data=data, headers={"Content-Type": "application/json"})

    t0 = time.perf_counter()
    first_token_time = None
    response_tokens = []
    total_duration_ns = 0
    eval_count = 0
    eval_duration_ns = 0

    with urllib.request.urlopen(req, timeout=60) as resp:
        for line in resp:
            if not line:
                continue
            chunk = json.loads(line.decode("utf-8"))
            token = chunk.get("response", "")
            if token and first_token_time is None:
                first_token_time = time.perf_counter()
            response_tokens.append(token)
            if chunk.get("done", False):
                total_duration_ns = chunk.get("total_duration", 0)
                eval_count = chunk.get("eval_count", len(response_tokens))
                eval_duration_ns = chunk.get("eval_duration", 0)

    t1 = time.perf_counter()
    full_text = "".join(response_tokens).strip()
    if "<think>" in full_text and "</think>" in full_text:
        full_text = re.sub(r'<think>.*?</think>', '', full_text, flags=re.DOTALL).strip()
    elif "</think>" in full_text:
        full_text = full_text.split("</think>")[-1].strip()
    
    ttft = (first_token_time - t0) if first_token_time is not None else (t1 - t0)
    total_time = t1 - t0
    
    if eval_duration_ns > 0 and eval_count > 0:
        tps = eval_count / (eval_duration_ns / 1e9)
    else:
        gen_time = max(total_time - ttft, 0.001)
        tps = max(eval_count, 1) / gen_time

    return {
        "text": full_text,
        "ttft_sec": ttft,
        "total_time_sec": total_time,
        "eval_count": eval_count,
        "tokens_per_sec": tps
    }

def evaluate_intent_routing(model):
    """Evaluates classification accuracy across the 10 intent prompts."""
    system_prompt = (
        "You are an intent classifier for a voice robotics assistant. "
        "Classify the user utterance into exactly one of three categories: "
        "hardware_intent, chat_response, or rag_search. "
        "Output ONLY the category name and nothing else."
    )
    correct = 0
    results = []

    for item in INTENT_PROMPTS:
        prompt = f"Utterance: \"{item['prompt']}\"\nCategory:"
        res = query_ollama_streaming(model, prompt, system_prompt=system_prompt)
        pred_raw = res["text"].lower().strip()
        
        # Normalize prediction
        pred = "unknown"
        if "hardware" in pred_raw:
            pred = "hardware_intent"
        elif "rag" in pred_raw or "search" in pred_raw:
            pred = "rag_search"
        elif "chat" in pred_raw or "response" in pred_raw:
            pred = "chat_response"

        is_correct = (pred == item["expected"])
        if is_correct:
            correct += 1

        results.append({
            "id": item["id"],
            "prompt": item["prompt"],
            "expected": item["expected"],
            "predicted": pred,
            "raw_output": res["text"],
            "correct": is_correct
        })

    accuracy = correct / len(INTENT_PROMPTS)
    return accuracy, results

def evaluate_json_formatting(model):
    """Evaluates JSON syntax validity and key presence on the 3 tool-call prompts."""
    valid_count = 0
    results = []

    system_prompt = "You are a tool execution planner. You must output strictly valid JSON with no markdown and no explanation."

    for item in JSON_TEST_PROMPTS:
        res = query_ollama_streaming(model, item["prompt"], system_prompt=system_prompt)
        text = res["text"].strip()
        # Clean markdown wrappers if present
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        is_valid = False
        parsed = None
        has_keys = False
        try:
            parsed = json.loads(text)
            has_keys = all(k in parsed for k in item["required_keys"])
            is_valid = has_keys
        except Exception:
            is_valid = False

        if is_valid:
            valid_count += 1

        results.append({
            "id": item["id"],
            "prompt": item["prompt"],
            "required_keys": item["required_keys"],
            "raw_output": res["text"],
            "is_valid": is_valid
        })

    validity_rate = valid_count / len(JSON_TEST_PROMPTS)
    return validity_rate, results

def evaluate_llm_model(model_name):
    print(f"\n=======================================================")
    print(f"  BENCHMARKING LOCAL LLM: {model_name} (Ollama on GPU)")
    print(f"=======================================================")

    vram_before = get_current_vram_mb()
    print(f"Initial VRAM before load: {vram_before:.1f} MB")

    # Check if model is pulled
    test_res = None
    try:
        test_res = query_ollama_streaming(model_name, "Say hello")
    except Exception as e:
        print(f"[SKIPPED] Model {model_name} not available in Ollama: {e}")
        return {
            "model": model_name,
            "status": "SKIPPED",
            "error": str(e)
        }

    vram_after = get_current_vram_mb()
    vram_delta = vram_after - vram_before
    print(f"Active VRAM footprint: {vram_after:.1f} MB (Delta: +{vram_delta:.1f} MB)")

    # 2 Warm-up runs
    for _ in range(2):
        try:
            query_ollama_streaming(model_name, "What is two plus two?")
        except Exception:
            pass

    # 5 Timed runs on standard conversational question
    bench_prompt = "Explain in two sentences how ultrasonic sensors detect obstacle distance for autonomous mobile robots."
    ttft_list = []
    tps_list = []

    for i in range(5):
        run_res = query_ollama_streaming(model_name, bench_prompt)
        ttft_list.append(run_res["ttft_sec"])
        tps_list.append(run_res["tokens_per_sec"])

    ttft_stats = stats(ttft_list)
    tps_stats = stats(tps_list)

    print(f"Speed Metrics for {model_name}:")
    print(f"  TTFT: {ttft_stats['median']*1000:.1f}ms (p95: {ttft_stats['p95']*1000:.1f}ms)")
    print(f"  Tokens/Sec: {tps_stats['median']:.1f} t/s (p95: {tps_stats['p95']:.1f} t/s)")

    # Intent routing accuracy (10 prompts)
    print(f"Evaluating intent routing across 10 prompts...")
    intent_acc, intent_details = evaluate_intent_routing(model_name)
    print(f"  Intent Routing Accuracy: {intent_acc * 100:.1f}% ({int(intent_acc * 10)}/10)")

    # JSON Tool-call formatting (3 prompts)
    print(f"Evaluating JSON format adherence across 3 prompts...")
    json_val, json_details = evaluate_json_formatting(model_name)
    print(f"  JSON Tool-Call Validity: {json_val * 100:.1f}% ({int(json_val * 3)}/3)")

    peak_vram = get_current_vram_mb()

    return {
        "model": model_name,
        "status": "COMPLETED",
        "ttft_median_ms": round(ttft_stats["median"] * 1000, 1),
        "ttft_p95_ms": round(ttft_stats["p95"] * 1000, 1),
        "tps_median": round(tps_stats["median"], 1),
        "tps_p95": round(tps_stats["p95"], 1),
        "peak_vram_mb": round(peak_vram, 1),
        "intent_accuracy": round(intent_acc, 3),
        "json_validity": round(json_val, 3),
        "sample_response": run_res["text"]
    }

def run_llm_benchmark(candidate_models=None):
    if candidate_models is None:
        candidate_models = ["llama3.2:3b", "llama3.1:8b", "phi4-mini", "qwen3:4b-instruct", "qwen3:8b"]

    print("=" * 70)
    print("            BUPI OFFLINE VOICE BENCHMARK: LOCAL LLMS")
    print("=" * 70)

    results = []
    for model in candidate_models:
        res = evaluate_llm_model(model)
        results.append(res)

    out_json = os.path.join(BENCH_DIR, "llm_results.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\n[Complete] LLM benchmark finished! Saved {len(results)} model records to {out_json}")
    return results

if __name__ == "__main__":
    models_to_run = sys.argv[1:] if len(sys.argv) > 1 else None
    run_llm_benchmark(models_to_run)
