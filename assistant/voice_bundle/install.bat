@echo off
title Bupi Voice Systems Installer

echo =========================================================
echo         BUPI VOICE SYSTEMS DEPENDENCY INSTALLER          
echo =========================================================
echo.

:: Detect the project virtual environment
set "VENV_DIR=%~dp0..\venv312"
set "PIP_BIN=pip"

if exist "%VENV_DIR%\Scripts\pip.exe" (
    echo [Environment] Detected virtual environment at: %VENV_DIR%
    set "PIP_BIN=%VENV_DIR%\Scripts\pip.exe"
) else (
    echo [Environment] Virtual environment not found at default location.
    echo               Will attempt installing to the system Python.
    echo.
)

echo [Install] Installing necessary voice processing libraries...
echo.

:: Run pip install commands
:: Note: webrtcvad-wheels is critical on Windows because it contains precompiled binaries 
:: and avoids the requirement of Microsoft C++ Build Tools to compile webrtcvad.
"%PIP_BIN%" install sounddevice numpy edge-tts requests python-dotenv faster-whisper webrtcvad-wheels PyQt6

if %ERRORLEVEL% equ 0 (
    echo.
    echo [SUCCESS] All python dependencies installed successfully!
    echo.
    echo Next Steps:
    echo  1. Make sure you have 'ffplay' installed on your system.
    echo     (Verify this by running: python diagnostics.py)
    echo  2. Run the speech-to-text listener:
    echo     python listener_demo.py
    echo  3. Run the text-to-speech speaker:
    echo     python speaker_demo.py "Hello, this is Bupi!"
    echo.
) else (
    echo.
    echo [ERROR] Installation failed. Please check your internet connection or python version.
    echo.
)

pause
