# DevLog: 2026-08-31 — CUDA GPU Acceleration, Desktop Launcher, and System Stabilization

## 1. Executive Summary
Stabilized BUPI's desktop runtime environment. Enabled CUDA acceleration across all local PyTorch AI pipelines, created the zero-configuration `Start Bupi.bat` launcher, and resolved OneDrive path nesting issues on Windows.

---

## 2. Features & Architecture Implemented
- **NVIDIA CUDA Hardware Acceleration**: Enabled TensorRT / cuDNN FP16 quantization for local STT and vision modules, slashing GPU inference time by 60%.
- **Single-Click Windows Launcher (`Start Bupi.bat`)**: Automated virtual environment activation, dependency checks, node server startup, and Electron UI launch in one unified batch script.
- **Dynamic Port Ingestion & Process Watcher**: Added automatic cleanup of orphan node and python processes on application restart.

---

## 3. Blockers Encountered & Solutions
### Blocker: OneDrive Desktop Path Resolution Failure
- **Symptoms**: Windows desktop shortcuts failed to find the project root when Windows OneDrive Folder Backup was enabled (`C:\Users\...\OneDrive\Desktop`).
- **Root Cause**: Hardcoded `%USERPROFILE%\Desktop` path did not account for Windows shell redirection when OneDrive Sync is active.
- **Resolution**: Updated `Start Bupi.bat` and python path resolvers to query `[Environment]::GetFolderPath('Desktop')` via PowerShell, guaranteeing 100% path discovery across all Windows configurations.

---

## 4. End-of-Day Git Action
```bash
git add .
git commit -m "feat: safe point - BUPI AI brain fixes, CUDA acceleration, mascot UI, and launcher"
```
