@echo off
title BUPI Robot Teleoperation Controller
cd /d "%~dp0"
if exist "%~dp0venv312\Scripts\python.exe" (
    "%~dp0venv312\Scripts\python.exe" scratch\test_drive.py
) else (
    python scratch\test_drive.py
)
pause
