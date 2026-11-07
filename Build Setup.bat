@echo off
title Build Flightdeck setup
cd /d "%~dp0"
where python >nul 2>nul && (python tools\build_setup.py) || (py -3 tools\build_setup.py)
echo.
pause
