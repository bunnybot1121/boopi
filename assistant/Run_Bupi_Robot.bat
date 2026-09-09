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

:: 3. Clear any stale background processes to guarantee fresh launch
taskkill /f /im electron.exe >nul 2>&1
taskkill /f /im python.exe >nul 2>&1

echo.
echo [Hardware] Connecting to ESP32 on COM3 and Wi-Fi Port 8767...
echo [Mode 2] Robotic Orchestration & Voice Mission Planner Ready!
echo.
echo Launching Boopi Desktop Application...
echo.

call npm start

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to start Boopi Desktop App.
    pause
)
