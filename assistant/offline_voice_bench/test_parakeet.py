import time
import onnx_asr

print("[Parakeet] Loading nemo-parakeet-tdt-0.6b-v3 (INT8 on CPU)...")
t0 = time.time()
model = onnx_asr.load_model("nemo-parakeet-tdt-0.6b-v3", quantization="int8", providers=["CPUExecutionProvider"])
t1 = time.time()
print(f"[Parakeet] Model loaded in {t1 - t0:.2f}s")

t2 = time.time()
res = model.recognize("offline_voice_bench/clips/clip_01.wav")
t3 = time.time()
print(f"[Parakeet] Transcribed clip_01 in {t3 - t2:.2f}s: '{res}'")
