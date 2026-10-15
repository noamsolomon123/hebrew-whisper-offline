@echo off
setlocal enableextensions
title Hebrew Whisper - self-test
chcp 65001 >nul
set "HW_ROOT=%~dp0"
set "HW_PY=%HW_ROOT%python\python.exe"
if not exist "%HW_PY%" (
  echo   python\python.exe is missing. Decode the bundle again.
  pause
  exit /b 1
)
"%HW_PY%" -X utf8 "%HW_ROOT%app\transcribe.py" --selftest
echo.
echo   Photograph this window and send it back.
pause
