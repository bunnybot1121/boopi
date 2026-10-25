"""
Benchmark utility functions: WER calculation, resource tracking (RAM, CPU, VRAM),
statistical aggregation (median, p95), and CSV logging.
"""

import os
import sys
import time
import subprocess
import psutil
import numpy as np

def compute_levenshtein(ref_words, hyp_words):
    """Calculates Levenshtein distance between two word sequences."""
    d = np.zeros((len(ref_words) + 1, len(hyp_words) + 1), dtype=int)
    for i in range(len(ref_words) + 1):
        d[i][0] = i
    for j in range(len(hyp_words) + 1):
        d[0][j] = j
        
    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            if ref_words[i - 1].lower() == hyp_words[j - 1].lower():
                d[i][j] = d[i - 1][j - 1]
            else:
                substitution = d[i - 1][j - 1] + 1
                insertion = d[i][j - 1] + 1
                deletion = d[i - 1][j] + 1
                d[i][j] = min(substitution, insertion, deletion)
    return d[len(ref_words)][len(hyp_words)]

def calculate_wer(reference: str, hypothesis: str) -> float:
    """Calculates Word Error Rate (WER)."""
    import string
    def clean(t):
        t = t.translate(str.maketrans("", "", string.punctuation))
        return [w.lower().strip() for w in t.split() if w.strip()]
    
    r_words = clean(reference)
    h_words = clean(hypothesis)
    
    if len(r_words) == 0:
        return 0.0 if len(h_words) == 0 else float(len(h_words))
        
    dist = compute_levenshtein(r_words, h_words)
    return float(dist) / float(len(r_words))

def get_current_vram_mb() -> float:
    """Queries NVIDIA-SMI for current VRAM usage in MB."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            encoding="utf-8"
        )
        return float(out.strip().split("\n")[0])
    except Exception:
        return 0.0

class ResourceMonitor:
    """Monitors peak RAM (MB) and average CPU % over an execution block."""
    def __init__(self):
        self.process = psutil.Process(os.getpid())
        self.initial_ram = self.process.memory_info().rss / (1024 * 1024)
        self.peak_ram = self.initial_ram
        self.cpu_samples = []
        self._running = False
        
    def start(self):
        self.process.cpu_percent(interval=None)
        self.initial_ram = self.process.memory_info().rss / (1024 * 1024)
        self.peak_ram = self.initial_ram
        self.cpu_samples = []
        self._running = True
        
    def sample(self):
        if not self._running:
            return
        mem = self.process.memory_info().rss / (1024 * 1024)
        if mem > self.peak_ram:
            self.peak_ram = mem
        cpu = self.process.cpu_percent(interval=None)
        if cpu > 0.0:
            self.cpu_samples.append(cpu)
            
    def stop(self):
        self.sample()
        self._running = False
        avg_cpu = sum(self.cpu_samples) / max(len(self.cpu_samples), 1)
        return {
            "peak_ram_mb": round(self.peak_ram, 1),
            "ram_delta_mb": round(self.peak_ram - self.initial_ram, 1),
            "avg_cpu_percent": round(avg_cpu, 1)
        }

def stats(values):
    """Returns median and p95 for a list of numeric values."""
    if not values:
        return {"median": 0.0, "p95": 0.0, "min": 0.0, "max": 0.0}
    arr = np.array(values, dtype=float)
    return {
        "median": round(float(np.median(arr)), 4),
        "p95": round(float(np.percentile(arr, 95)), 4),
        "min": round(float(np.min(arr)), 4),
        "max": round(float(np.max(arr)), 4)
    }
