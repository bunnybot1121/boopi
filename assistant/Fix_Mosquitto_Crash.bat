@echo off
:: Check for admin rights
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo Fixing Mosquitto configuration...
findstr /v /c:"listener 1883" /c:"allow_anonymous true" /c:"listener 9001" /c:"protocol websockets" "C:\Program Files\mosquitto\mosquitto.conf" > "%temp%\mosquitto.conf.tmp"
echo listener 1883 >> "%temp%\mosquitto.conf.tmp"
echo allow_anonymous true >> "%temp%\mosquitto.conf.tmp"
echo. >> "%temp%\mosquitto.conf.tmp"
echo listener 9001 >> "%temp%\mosquitto.conf.tmp"
echo protocol websockets >> "%temp%\mosquitto.conf.tmp"
echo allow_anonymous true >> "%temp%\mosquitto.conf.tmp"

move /y "%temp%\mosquitto.conf.tmp" "C:\Program Files\mosquitto\mosquitto.conf"

echo Configuring Mosquitto for delayed-auto start and auto-restart recovery...
sc config mosquitto start= delayed-auto
sc failure mosquitto reset= 86400 actions= restart/5000/restart/5000/restart/5000

echo.
echo Fix applied! The broker is configured with delayed-auto startup, auto-restart, and Websocket port 9001.
pause
