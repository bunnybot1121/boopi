@echo off
:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo Adding configuration to mosquitto.conf...
echo. >> "C:\Program Files\mosquitto\mosquitto.conf"
echo listener 1883 >> "C:\Program Files\mosquitto\mosquitto.conf"
echo allow_anonymous true >> "C:\Program Files\mosquitto\mosquitto.conf"

echo Restarting Mosquitto Service...
net stop mosquitto
net start mosquitto

echo.
echo Mosquitto setup is complete! Hive Mind Broker is fully running.
pause
