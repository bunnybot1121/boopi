@echo off
cd /d "%~dp0"
title Bupi - Desktop AI Companion
echo ==============================================
echo   Starting Bupi Desktop AI Companion...
echo ==============================================
echo.

:: 1. Clear any stale Boopi zombie processes & release Port 8767
echo [1/5] Cleaning up any stale Boopi background processes...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'run_mode2|bupi_node_server|boopi.*main\.py' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }; " ^
    "Get-NetTCPConnection -LocalPort 8767 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

:: 2. Verify Mosquitto MQTT Broker
echo [2/5] Verifying Mosquitto MQTT Broker...
sc query mosquitto | find "RUNNING" >nul
if %errorlevel% neq 0 (
    echo [System] Starting Mosquitto MQTT Broker...
    net start mosquitto >nul 2>&1
)

:: 3. Verify Windows Mobile Hotspot for ESP32 Robots
echo [3/5] Verifying Windows Mobile Hotspot for ESP32 Robots...
call powershell -ExecutionPolicy Bypass -File "%~dp0scripts\ensure_hotspot.ps1"

:: 4. Verify & Pre-Warm Ollama in background (keeps model hot in VRAM)
echo [4/5] Pre-warming Ollama AI model in GPU VRAM...
tasklist /fi "ImageName eq ollama.exe" 2>NUL | find /i "ollama.exe" >nul
if %errorlevel% neq 0 (
    where ollama >nul 2>&1
    if %errorlevel% equ 0 (
        start /b "" ollama serve >nul 2>&1
        timeout /t 2 /nobreak >nul 2>&1
    )
)
powershell -NoProfile -Command "Start-Job -ScriptBlock { try { Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/generate' -Method Post -Body '{\"model\":\"llama3.2:3b\",\"keep_alive\":-1}' -ContentType 'application/json' -TimeoutSec 30 } catch {} }" >nul 2>&1

:: 5. Verify venv312 and Electron dependencies
if not exist "%~dp0venv312\Scripts\python.exe" (
    echo [ERROR] Python 3.12 virtual environment (venv312) missing!
    echo Please ensure venv312 is configured at "%~dp0venv312".
    pause
    exit /b
)

if not exist "%~dp0node_modules\electron\dist\electron.exe" (
    echo [System] Electron dependencies missing. Installing...
    call npm install
)

echo [5/5] Launching Boopi Desktop Application...
echo.
call .\node_modules\electron\dist\electron.exe . --mode 1

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Bupi exited with an error.
    pause
)
