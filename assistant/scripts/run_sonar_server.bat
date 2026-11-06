@echo off
TITLE BUPI Sonar Vision & Spatial DIP Server
cd /d "%~dp0\.."
echo ============================================================
echo   BUPI Ultrasonic Vision 2.5D/3D Server
echo   Running at http://localhost:8050
echo ============================================================
echo.
python -m uvicorn bupi_phase1_sonar_test.backend.server:app --port 8050 --host 0.0.0.0
pause

