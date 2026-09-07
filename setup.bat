@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
title cursor-crew-bridge setup
if /i "%~1"=="nopause" set "SKIPPAUSE=1"

where python >nul 2>nul
if errorlevel 1 (
  echo Python is not on PATH.
  echo Install Python 3.11+ from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  if not defined SKIPPAUSE pause
  exit /b 1
)

if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Creating .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv
    if not defined SKIPPAUSE pause
    exit /b 1
  )
)

echo Installing cursor-crew-bridge into .venv ...
"%~dp0.venv\Scripts\python.exe" -m pip install -U pip
if errorlevel 1 goto :fail
"%~dp0.venv\Scripts\python.exe" -m pip install -e .
if errorlevel 1 goto :fail

"%~dp0.venv\Scripts\python.exe" -m cursor_crew_bridge.cli setup --no-install
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" goto :fail

echo.
echo Next: double-click start-cursor-gateway.bat
if not defined SKIPPAUSE pause
endlocal
exit /b 0

:fail
echo Setup did not finish. Run:  .venv\Scripts\python.exe -m cursor_crew_bridge.cli doctor
if not defined SKIPPAUSE pause
endlocal
exit /b 1
