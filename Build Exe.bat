@echo off
title Build Flightdeck.exe
cd /d "%~dp0"
setlocal

rem --- needs Python on THIS pc only; the finished exe needs nothing ----------
set "PY=python"
where python >nul 2>nul || set "PY=py -3"

echo.
echo  [1/3] Preparing a private build environment (first time takes a minute)...
if not exist ".buildenv\Scripts\python.exe" %PY% -m venv .buildenv || goto :fail
".buildenv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check --upgrade pip pyinstaller zstandard qrcode || goto :fail

echo  [2/3] Building Flightdeck.exe...
set "HERE=%~dp0"
".buildenv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --console ^
  --name Flightdeck ^
  --icon "%HERE%installer\flightdeck.ico" ^
  --add-data "%HERE%static;static" ^
  --add-data "%HERE%sc_data;sc_data" ^
  --add-data "%HERE%config.json;." ^
  --hidden-import server --hidden-import userdata --hidden-import market --hidden-import mirror --hidden-import sc_bindings ^
  --hidden-import zstandard --hidden-import qrcode ^
  --exclude-module tkinter ^
  --paths "%HERE%." ^
  --distpath "%HERE%dist" --workpath "%HERE%build\pyinstaller" --specpath "%HERE%build" ^
  "%HERE%flightdeck.py" || goto :fail

echo  [3/3] Done.
echo.
echo    %HERE%dist\Flightdeck.exe
echo.
echo  Copy Flightdeck.exe to any folder on any Windows PC and double-click it.
echo  No Python or installer needed. Settings are kept next to the exe.
echo.
pause
exit /b 0

:fail
echo.
echo  Build failed - see the messages above.
pause
exit /b 1
