@echo off
:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo Fixing Mosquitto configuration...
findstr /v /c:"listener 1883" /c:"allow_anonymous true" "C:\Program Files\mosquitto\mosquitto.conf" > "%temp%\mosquitto.conf.tmp"
echo listener 1883 >> "%temp%\mosquitto.conf.tmp"
echo allow_anonymous true >> "%temp%\mosquitto.conf.tmp"

move /y "%temp%\mosquitto.conf.tmp" "C:\Program Files\mosquitto\mosquitto.conf"

echo Restarting Mosquitto Service...
net start mosquitto

echo.
echo Fix applied! The broker should be running now.
pause
