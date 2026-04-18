@echo off
title Build Compy Executable
echo ==============================================
echo Preparing to Build Compy...
echo ==============================================

rem Check if python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in your PATH.
    pause
    exit /b
)

echo Installing PyInstaller and Dependencies...
pip install pyinstaller
pip install -r requirements.txt

echo ==============================================
echo Building the executable...
echo ==============================================
rem We use --windowed to hide the console since it's a desktop character companion
rem We use --add-data to package the 'assets' and 'memory' directories alongside 
rem Note: In Windows, the separator for add-data is a semicolon ';'
pyinstaller --noconfirm --windowed --name "Compy" --add-data "assets;assets" --add-data ".env;." main.py

echo ==============================================
echo Build Complete!
echo You can find your new Compy.exe inside the 'dist/Compy' folder!
echo ==============================================
pause
