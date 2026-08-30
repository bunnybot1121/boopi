# BUPI Project Improvement Plan & Strategic Roadmap

This document outlines key technical improvements and strategic enhancements identified across the **BUPI (Boopi)** codebase. Recommendations are categorized by domain to help evaluate priorities and impact.

---

## 1. GPU Acceleration & Local Hardware Optimization

| Feature / Improvement | Problem / Context | Proposed Solution | Expected Impact |
| :--- | :--- | :--- | :--- |
| **CUDA PyTorch & ONNX Runtime Enablement** | Python 3.14 was running the CPU-only PyTorch build, causing local speech/embeddings to rely on CPU execution. | Install CUDA 12-enabled PyTorch (`torch+cu124`) and `onnxruntime-gpu` / `ctranslate2` to offload local Faster-Whisper and vector embeddings to the **NVIDIA GeForce RTX 4050 GPU**. | **3x-5x faster** local transcription & zero CPU bottleneck during voice processing. |
| **Ollama GPU Memory Locking & Context Caching** | Local Ollama models load/unload between idle states if VRAM is shared. | Configure `OLLAMA_NUM_PARALLEL=1` and `OLLAMA_KEEP_ALIVE=24h` in system environment variables to keep models pre-warmed in RTX 4050 VRAM. | Eliminates 2-3s model cold-start delay during offline generation. |

---

## 2. AI Brain & Function Calling Architecture

| Feature / Improvement | Problem / Context | Proposed Solution | Expected Impact |
| :--- | :--- | :--- | :--- |
| **Structured JSON Tool Calling** | Custom regex tag parsing (e.g., `[ACTION: ...]`, `[NOTEPAD]`) can sometimes fail if an LLM formats brackets slightly differently. | Standardize action execution using native LLM Function/Tool Calling schemas (OpenAI / Gemini / Ollama tools API). | Zero parsing errors and precise system action dispatching. |
| **Context Window Compression & Sliding Windowing** | Long conversation histories (>30 turns) increase prompt token size and slow down response time. | Implement sliding-window history combined with automatic background memory summarization (`MemorySummaryService`). | Maintains fixed <1k prompt token overhead regardless of session length. |
| **Multimodal Vision Stream Pipeline** | Vision queries currently capture one-off manual screenshots (`take_screenshot`). | Add an option for low-framerate (1 fps) continuous screen perception when BUPI is in active assistant mode. | Enables proactive assistance (e.g., BUPI noticing a code error on screen before you ask). |

---

## 3. Voice & Audio Processing Pipeline

| Feature / Improvement | Problem / Context | Proposed Solution | Expected Impact |
| :--- | :--- | :--- | :--- |
| **Acoustic Echo Cancellation (AEC)** | When BUPI speaks through loud speakers, the microphone can re-capture the TTS audio and self-trigger. | Implement PyAudio / WebRTC AEC audio stream filtering to subtract active TTS playback audio from incoming microphone signals. | Prevents feedback loops and allows seamless barge-in interruption while BUPI is speaking. |
| **Native Offline TTS Engine (Kokoro / Piper)** | Edge-TTS requires an active internet connection to synthesize voice audio. | Integrate **Kokoro-TTS** or **Piper-TTS** as a local GPU/CPU fallback TTS engine. | 100% offline text-to-speech functionality with ultra-natural voice quality. |
| **Dynamic VAD Sensitivity Tuning** | Fixed VAD threshold can cut off speech in noisy rooms or miss quiet speech. | Implement adaptive noise floor tracking during speech listening loops. | Higher speech recognition accuracy in noisy ambient environments. |

---

## 4. UI/UX & Desktop Mascot Visuals

| Feature / Improvement | Problem / Context | Proposed Solution | Expected Impact |
| :--- | :--- | :--- | :--- |
| **Transparent Floating Desktop Companion Mode** | Electron window currently operates in a fixed framed or frameless container. | Add a click-through toggle (`setIgnoreMouseEvents(true)`) allowing BUPI to float directly on top of IDEs and browsers without blocking mouse clicks. | True desktop mascot experience (lives alongside your work). |
| **Live Audio Spectrum Visualizer** | Thought bubble shows static text or simple SVG face states. | Integrate Web Audio API frequency analyzer canvas behind the mascot during listening/speaking states. | Modern, dynamic visual feedback while BUPI is processing speech. |
| **Interactive Avatar Physics (3D / Live2D)** | SVG avatar animations are frame-based sequences. | Support Rive / Live2D avatar skeletal animation with real-time mouse gaze tracking. | Avatar turns head and follows your mouse cursor across the screen. |

---

## 5. Robotics & Hardware Integration (Mode 2 / ESP32)

| Feature / Improvement | Problem / Context | Proposed Solution | Expected Impact |
| :--- | :--- | :--- | :--- |
| **Bi-Directional MQTT Heartbeat & Auto-Reconnect** | If WiFi drops, MQTT node loses connection without automatic fallback. | Implement automatic failover from MQTT to USB Serial (`esp32_bwe_mqtt_client.ino`) when network ping fails. | Guaranteed command delivery to physical motors and sensors. |
| **Real-Time Telemetry Dashboard** | Sensor readings (MQ2 gas, MPU6050 tilt, motor status) are printed in terminal logs. | Create a dedicated visual Telemetry Widget inside the Electron GUI to display live gauge charts. | Instant visual monitoring of BUPI's hardware state. |
| **Hardware Emergency Stop (E-Stop)** | No instant hardware override button in the UI. | Add a prominent global hotkey (e.g. `Ctrl+Alt+S`) and UI button to immediately send `[ACTION: STOP_MOTORS]` via MQTT/Serial. | Protects hardware from accidental wall bumps or runaway motor loops. |

---

## 6. System Security & Diagnostics

| Feature / Improvement | Problem / Context | Proposed Solution | Expected Impact |
| :--- | :--- | :--- | :--- |
| **Health & Diagnostic Panel** | API key failures or model disconnects require reading python log files. | Add a built-in System Status modal in the GUI showing status lights for Groq, Gemini, Ollama, PyTorch CUDA, and MQTT. | One-click diagnostic status for all system services. |
| **Secure API Key Encryption** | API keys are stored in plain text inside `.env`. | Provide optional Windows Credential Manager integration for storing cloud API tokens securely. | Production-grade security for sensitive environment keys. |

---

## Priority Assessment & Implementation Matrix

| Phase | Recommendation Focus | Key Deliverables | Effort | Impact |
| :--- | :--- | :--- | :--- | :--- |
| **Phase 1 (Immediate)** | GPU Acceleration & Latency | Complete CUDA installation, pre-warm Ollama VRAM, tune VAD thresholds. | Low | **High** |
| **Phase 2 (Near-Term)** | UI & Voice Upgrades | Transparent Click-Through mode, AEC Echo Cancellation, Health Diagnostic GUI. | Medium | **High** |
| **Phase 3 (Long-Term)** | Advanced AI & Robotics | Structured JSON tool schemas, Live2D avatar gaze tracking, Hardware E-Stop hotkey. | Medium | Medium |

