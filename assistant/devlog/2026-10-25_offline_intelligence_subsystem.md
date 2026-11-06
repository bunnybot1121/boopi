# DevLog: 2026-10-25 — 100% Offline AI Subsystem (Ollama, Faster-Whisper, Piper) & Latency Optimization

## 1. Executive Summary
Achieved complete offline capability for BUPI. Eliminated all cloud dependencies so the entire robot can operate autonomously in subterranean and zero-connectivity disaster zones. Optimized Time-To-First-Token (TTFT) to under 770ms and resolved electron single-instance lock deadlocks.

---

## 2. Features & Architecture Implemented
- **100% Offline Model Subsystem**:
  - **Local LLM**: Ollama with quantized Qwen / Llama 3 running fully on edge GPU/CPU.
  - **Local STT**: Faster-Whisper INT8 quantization with direct audio ring buffers.
  - **Local TTS**: Piper neural voice engine delivering ultra-fast phoneme speech synthesis without internet.
- **Thinking Timeout Hang Fix**: Optimized prompt structure and added streaming cancel token to prevent long thinking loops from delaying physical robot commands.
- **Automated Verification Suite (`tests/test_offline_stack.py`)**: Unit and integration tests verifying offline STT/TTS toggle flags and pipeline latency metrics.

---

## 3. Blockers Encountered & Solutions
### Blocker 1: Electron Single-Instance Mutex Collision (`duplicate gotTheLock declaration`)
- **Symptoms**: Electron application refused to launch or crashed on startup with `SyntaxError: Identifier 'gotTheLock' has already been declared`.
- **Root Cause**: Two nested conditional blocks in `main.js` both attempted to declare `const gotTheLock = app.requestSingleInstanceLock()`.
- **Resolution**: Refactored `main.js` to declare a single top-level mutex guard at entry point, terminating duplicate processes cleanly.

### Blocker 2: Audio Device Lock Contention in Offline TTS
- **Symptoms**: Piper TTS failed to play audio when Faster-Whisper was listening to the microphone.
- **Root Cause**: Windows DirectSound exclusive access lock was being held by PyAudio.
- **Resolution**: Shared WASAPI audio device streams across processes using dedicated non-exclusive audio pipelines.

---

## 4. End-of-Day Git Action
```bash
git add .
git commit -m "fix(offline): Fix offline STT boolean toggle and add test_offline_stack suite"
```

