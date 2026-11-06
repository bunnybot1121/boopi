# DevLog: 2026-05-20 — Hybrid LLM Router, Whisper STT, and Desktop Automation Core

## 1. Executive Summary
Established the primary software core for BUPI's desktop companion layer. Built the hybrid LLM routing engine that balances low-latency edge models with high-reasoning cloud failover, integrated local Whisper speech-to-text, and built desktop system automations.

---

## 2. Features & Architecture Implemented
- **Hybrid LLM Router (`core/llm_router.py`)**: Automatic intent classifier routing fast operational commands to local small models and complex planning queries to larger reasoning models.
- **Local Speech-to-Text Pipeline**: Deployed `whisper small.en` running locally on CPU/GPU for instant speech transcription without external network dependence.
- **Built-in Terminal Log Streaming**: Real-time log capture and ANSI color parsing piped directly into the desktop UI console.
- **System Automations**: Initial automation primitives for messaging workflows (WhatsApp automation bridge) and local application control.

---

## 3. Blockers Encountered & Solutions
### Blocker: Audio Buffer Latency & Transcription Lag
- **Symptoms**: Speech transcription lagged behind spoken sentences by over 3.2 seconds.
- **Root Cause**: Whisper small was waiting for entire 30-second audio buffers before inference.
- **Resolution**: Implemented dynamic Voice Activity Detection (VAD) slicing and streamed 1.5-second chunks with overlap merging, reducing transcription latency under 800ms.

---

## 4. End-of-Day Git Action
```bash
git add .
git commit -m "feat: Add Hybrid LLM Router, Whisper small.en, and built-in Terminal logs"
```
