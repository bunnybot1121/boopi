@echo off
echo ==================================================
echo   BWE HIL Device-in-the-Loop Bridge Launcher
echo ==================================================
echo.

:: 1. Check for Python
python --version >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Python is not installed or not in your system PATH.
    echo Please install Python and try again.
    pause
    exit /b
)

:: 2. Install dependencies
echo Checking and installing Python dependencies...
python -m pip install pyserial paho-mqtt
if %errorLevel% neq 0 (
    echo [Warning] Failed to verify packages via standard pip. Attempting fallback...
)

echo.
echo ==================================================
echo   Starting HIL Serial-to-MQTT Bridge...
echo ==================================================
echo.

:: 3. Run the bridge
python "%~dp0bwe_serial_mqtt_bridge.py"

pause
