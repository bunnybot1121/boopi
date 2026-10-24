@echo off
cd /d "%~dp0"
title BUPI Autonomous Robot & Desktop AI Companion
echo ========================================================
echo        🤖 BUPI ROBOT & DESKTOP AI COMPANION (MODE 2)
echo ========================================================
echo.

:: 1. Verify Mosquitto MQTT Broker
sc query mosquitto | find "RUNNING" >nul
if %errorlevel% neq 0 (
    echo [System] Starting Mosquitto MQTT Broker...
    net start mosquitto >nul 2>&1
)

:: 2. Verify Ollama Local LLM
tasklist /fi "ImageName eq ollama.exe" 2>NUL | find /i "ollama.exe" >nul
if %errorlevel% neq 0 (
    echo [System] Starting Ollama Local LLM in background...
    start /b "" ollama serve >nul 2>&1
)

:: 3. Verify Windows Mobile Hotspot for ESP32 Robots
call powershell -ExecutionPolicy Bypass -File "%~dp0scripts\ensure_hotspot.ps1"

:: 4. Clear any stale Boopi background processes & release Port 8767
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'run_mode2|bupi_node_server|boopi.*main\.py' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; " ^
    "Get-NetTCPConnection -LocalPort 8767 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

:: Pre-warm Ollama AI model in GPU VRAM
powershell -NoProfile -Command "Start-Job -ScriptBlock { try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/generate' -Method Post -Body '{\"model\":\"llama3.2:3b\",\"keep_alive\":-1}' -ContentType 'application/json' -TimeoutSec 30 } catch {} }" >nul 2>&1

echo.
echo [Hardware] Connecting to ESP32 on COM3 and Wi-Fi Port 8767...
echo [Mode 2] Robotic Orchestration & Voice Mission Planner Ready!
echo.
echo Launching Boopi Desktop Application...
echo.

call .\node_modules\electron\dist\electron.exe . --mode 2

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to start Boopi Desktop App.
    pause
)
