@echo off
title Flightdeck
cd /d "%~dp0"
where python >nul 2>nul || (echo Python not found. Install from https://www.python.org/downloads/ and tick "Add to PATH". & pause & exit /b)
python -c "import zstandard, qrcode" 2>nul || (echo First run: installing zstandard and qrcode - lets Flightdeck read Star Citizen's default keybinds and show a QR code... & python -m pip install --quiet --disable-pip-version-check zstandard qrcode)
rem flightdeck.py finds Star Citizen, offers to open the firewall once, shows the iPad address, then starts server.py
python flightdeck.py
pause
