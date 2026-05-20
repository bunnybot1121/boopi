@echo off
title Bupi Launcher
cd /d "%~dp0"

echo ============================================
echo     Bupi Companion - Launcher Starting
echo ============================================
echo.
echo Bupi will appear in your System Tray.
echo Left-click the tray icon to open the menu.
echo Right-click for quick Launch/Quit options.
echo.
echo ============================================

start "" /b ".\node_modules\electron\dist\electron.exe" launcher.js

timeout /t 2 /nobreak >nul
exit
