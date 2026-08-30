@echo off
cd /d "%~dp0"

set "APP_DIR=%~dp0"
set "ELECTRON_EXE=%APP_DIR%node_modules\electron\dist\electron.exe"
set "LAB_JS=%APP_DIR%launch_bwe_lab.js"
set "ICO_FILE=%APP_DIR%assets\app_icon.ico"

echo.
echo ================================================
echo   BWE Laboratory Desktop Shortcut Installer
echo ================================================
echo.

:: Create the desktop shortcut
echo Creating desktop shortcut...

set "USE_ICON=%ICO_FILE%"
if not exist "%ICO_FILE%" set "USE_ICON=%ELECTRON_EXE%,0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$desktop = [Environment]::GetFolderPath('Desktop'); " ^
  "$sc = $ws.CreateShortcut(\"$desktop\BWE Laboratory.lnk\"); " ^
  "$sc.TargetPath = '%ELECTRON_EXE%'; " ^
  "$sc.Arguments = [char]34 + '%LAB_JS%' + [char]34; " ^
  "$sc.WorkingDirectory = '%APP_DIR%'; " ^
  "$sc.IconLocation = '%USE_ICON%'; " ^
  "$sc.Description = 'BUPI World Engine - Virtual Robotics & IoT Laboratory'; " ^
  "$sc.Save(); " ^
  "if (Test-Path \"$desktop\BWE Laboratory.lnk\") { Write-Host 'SUCCESS' } else { Write-Host 'FAILED' }"

echo.
