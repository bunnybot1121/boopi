@echo off
:: BUPI Windows Mobile Hotspot Idle-Timeout Fix
:: Disables Windows from automatically shutting off the Mobile Hotspot after 5 minutes of inactivity.

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [System] Requesting Administrator privileges to update hotspot registry...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~dp0Fix_Hotspot_Timeout.bat\"' -Verb RunAs"
    exit /b
)

title BUPI - Fix Windows Mobile Hotspot Timeout
echo ========================================================
echo   ⚡ DISABLING WINDOWS 11 MOBILE HOTSPOT AUTO-TIMEOUT
echo ========================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "try { " ^
    "    Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings' -Name 'PeerlessTimeoutEnabled' -Value 0 -Type DWord -Force; " ^
    "    Write-Host '[SUCCESS] PeerlessTimeoutEnabled set to 0 (Disabled auto-turnoff).' -ForegroundColor Green; " ^
    "    Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\icssvc\Settings' -Name 'PublicConnectionTimeout' -Value 60 -Type DWord -Force -ErrorAction SilentlyContinue; " ^
    "    Write-Host '[SUCCESS] PublicConnectionTimeout extended to 60 minutes.' -ForegroundColor Green; " ^
    "} catch { " ^
    "    Write-Host '[ERROR] Failed to update registry: ' $_ -ForegroundColor Red; " ^
    "}"

echo.
echo ========================================================
echo Mobile Hotspot will now stay ON permanently for robots!
echo ========================================================
echo.
pause
