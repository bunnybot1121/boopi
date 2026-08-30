@echo off
cd /d "%~dp0"
title Bupi - Desktop AI Companion
echo ==============================================
echo   Starting Bupi Desktop AI Companion...
echo ==============================================

:: Check if node_modules exists
if not exist "%~dp0node_modules\electron\dist\electron.exe" (
    echo [ERROR] Electron dependencies missing. Installing dependencies...
    call npm install
)

:: Launch BUPI via electron wrapper
call npm start

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Bupi failed to start.
    pause
)
