@echo off
:: ============================================================
:: Bupi - Create Desktop Shortcut
:: Run this ONCE to install a proper desktop icon for Bupi
:: ============================================================
cd /d "%~dp0"

set "APP_DIR=%~dp0"
set "ELECTRON_EXE=%APP_DIR%node_modules\electron\dist\electron.exe"
set "LAUNCHER_JS=%APP_DIR%launcher.js"
set "ICO_FILE=%APP_DIR%assets\app_icon.ico"
set "PNG_FILE=%APP_DIR%assets\app_icon.png"
set "SHORTCUT=%USERPROFILE%\Desktop\Bupi.lnk"

echo.
echo ================================================
echo   Bupi Desktop Shortcut Installer
echo ================================================
echo.

:: Step 1: Convert PNG to ICO using PowerShell + .NET
echo [1/2] Converting icon to Windows ICO format...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Add-Type -AssemblyName System.Drawing; " ^
  "$png = [System.Drawing.Image]::FromFile('%PNG_FILE%'); " ^
  "$bmp = New-Object System.Drawing.Bitmap 256, 256; " ^
  "$g = [System.Drawing.Graphics]::FromImage($bmp); " ^
  "$g.DrawImage($png, 0, 0, 256, 256); " ^
  "$g.Dispose(); " ^
  "$icon = [System.Drawing.Icon]::FromHandle($bmp.GetHicon()); " ^
  "$fs = New-Object System.IO.FileStream('%ICO_FILE%', [System.IO.FileMode]::Create); " ^
  "$icon.Save($fs); " ^
  "$fs.Close(); " ^
  "$icon.Dispose(); " ^
  "$bmp.Dispose(); " ^
  "$png.Dispose(); " ^
  "Write-Host 'Icon converted successfully.'"

:: Step 2: Create the desktop shortcut
echo [2/2] Creating desktop shortcut...

set "USE_ICON=%ICO_FILE%"
if not exist "%ICO_FILE%" set "USE_ICON=%ELECTRON_EXE%,0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$desktop = [Environment]::GetFolderPath('Desktop'); " ^
  "$shortcutPath = Join-Path $desktop 'Bupi.lnk'; " ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$sc = $ws.CreateShortcut($shortcutPath); " ^
  "$sc.TargetPath = '%ELECTRON_EXE%'; " ^
  "$sc.Arguments = [char]34 + '%APP_DIR%' + [char]34; " ^
  "$sc.WorkingDirectory = '%APP_DIR%'; " ^
  "$sc.IconLocation = '%USE_ICON%'; " ^
  "$sc.Description = 'Bupi - Desktop AI Companion'; " ^
  "$sc.Save(); " ^
  "Write-Host ('Shortcut created at: ' + $shortcutPath)"

echo.
if exist "%SHORTCUT%" (
    echo ================================================
    echo   SUCCESS!
    echo   "Bupi" shortcut added to your Desktop.
    echo   Double-click it anytime to start Bupi!
    echo ================================================
) else (
    echo [ERROR] Shortcut could not be created.
    echo Please run this as Administrator and try again.
)

echo.
pause
