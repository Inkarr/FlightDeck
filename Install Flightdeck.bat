@echo off
title Flightdeck installer
cd /d "%~dp0"

rem --- ask for administrator rights if we don't have them --------------------
net session >nul 2>&1
if errorlevel 1 (
    echo Asking Windows for administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

rem --- files from a downloaded zip are "blocked" by Windows; unblock them ----
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0' -Recurse -File | Unblock-File"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\install.ps1"
if errorlevel 1 (
    echo.
    echo Something went wrong - see the message above.
)
echo.
pause
