@echo off
cd /d "%~dp0"
title Flash BUPI Bot 1 (Scout)
echo ========================================================
echo     [FLASHING] BUPI BOT 1 (SCOUT) FIRMWARE
echo ========================================================
echo.
echo Please ensure Bot 1 is connected via USB cable.
echo.
set PORT=COM3
if not "%~1"=="" set PORT=%~1
echo Target Port: %PORT%
echo.
echo ========================================================
echo  CRITICAL: When the screen shows "Connecting........"
echo  PRESS AND HOLD the [BOOT] button on your ESP32 board
echo  for 1-2 seconds until the upload starts!
echo ========================================================
echo.

:: Release any serial port lock held by background bridge or Arduino IDE Serial Monitor
taskkill /f /im python.exe >nul 2>&1
taskkill /f /im serial-monitor.exe >nul 2>&1
timeout /t 1 /nobreak >nul

arduino-cli compile --upload -p %PORT% --fqbn esp32:esp32:esp32 firmware/bupi_bot1_scout
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Upload failed on %PORT%.
    echo Check Device Manager for the correct CP210x COM port.
    echo Usage: Flash_Bot1.bat COMx
    pause
    exit /b 1
)
echo.
echo [SUCCESS] Bot 1 (Scout) Flashed successfully!
pause
