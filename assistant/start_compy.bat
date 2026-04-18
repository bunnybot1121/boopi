@echo off
cd /d "%~dp0"
title Compy - Desktop Companion
echo ==============================================
echo Preparing Compy Environment...
echo ==============================================

rem Check if python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in your PATH.
    pause
    exit /b
)

echo Checking dependencies...
pip install -r requirements.txt

echo ==============================================
echo Starting Compy Electron Wrapper...
echo ==============================================
npm start

pause
