@echo off
TITLE BUPI Daily DevLog & Git Sync
cd /d "%~dp0\.."
echo ============================================================
echo   BUPI Automated DevLog & Git Sync Launcher
echo ============================================================
echo.
python scripts\auto_devlog_sync.py --push
echo.
pause
