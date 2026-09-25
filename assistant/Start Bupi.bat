@echo off
cd /d "%~dp0"
title Bupi - Desktop AI Companion
echo ==============================================
echo   Starting Bupi Desktop AI Companion...
echo ==============================================

:: 1. Verify Mosquitto MQTT Broker
sc query mosquitto | find "RUNNING" >nul
if %errorlevel% neq 0 (
    echo [System] Starting Mosquitto MQTT Broker...
    net start mosquitto >nul 2>&1
)

:: 2. Verify Ollama Local LLM (if installed)
tasklist /fi "ImageName eq ollama.exe" 2>NUL | find /i "ollama.exe" >nul
if %errorlevel% neq 0 (
    where ollama >nul 2>&1
    if %errorlevel% equ 0 (
        echo [System] Starting Ollama Local LLM in background...
        start /b "" ollama serve >nul 2>&1
    )
)

:: 3. Check if node_modules exists
if not exist "%~dp0node_modules\electron\dist\electron.exe" (
    echo [ERROR] Electron dependencies missing. Installing dependencies...
    call npm install
)

:: 4. Verify Windows Mobile Hotspot for ESP32 Robots
call powershell -ExecutionPolicy Bypass -File "%~dp0scripts\ensure_hotspot.ps1"

:: Launch BUPI via electron wrapper (Default: Mode 1 Conversational)
call .\node_modules\electron\dist\electron.exe . --mode 1

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Bupi failed to start.
    pause
)
