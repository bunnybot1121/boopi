@echo off
echo ==================================================
echo   BWE HIL Device-in-the-Loop Bridge Launcher
echo ==================================================
echo.

:: 1. Check for dedicated venv312 Python
if not exist "%~dp0venv312\Scripts\python.exe" (
    echo [ERROR] Dedicated Python virtual environment (venv312) not found.
    echo Please ensure venv312 is present at "%~dp0venv312".
    pause
    exit /b
)

set "PY_EXE=%~dp0venv312\Scripts\python.exe"

:: 2. Install dependencies via venv312
echo Checking and installing Python dependencies in venv312...
"%PY_EXE%" -m pip install pyserial paho-mqtt
if %errorLevel% neq 0 (
    echo [Warning] Failed to verify packages via venv pip.
)

echo.
echo ==================================================
echo   Starting HIL Serial-to-MQTT Bridge...
echo ==================================================
echo.

:: 3. Run the bridge
"%PY_EXE%" "%~dp0bwe_serial_mqtt_bridge.py"

pause
