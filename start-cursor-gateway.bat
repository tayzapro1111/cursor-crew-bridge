@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
title KiroCrew Cursor Gateway
if /i "%~1"=="nopause" set "SKIPPAUSE=1"
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Missing %PY%
  echo Run setup.bat first.
  if not defined SKIPPAUSE pause
  exit /b 1
)
"%PY%" -m cursor_crew_bridge.cli gateway
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo Launch failed. Exit code %ERR%.
  if not defined SKIPPAUSE pause
  exit /b %ERR%
)
if not defined SKIPPAUSE pause
endlocal
