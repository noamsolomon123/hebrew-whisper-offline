@echo off
setlocal enableextensions
title Hebrew Whisper - transcribe
chcp 65001 >nul
set "HW_ROOT=%~dp0"
set "HW_PY=%HW_ROOT%python\python.exe"
if not exist "%HW_PY%" (
  echo   python\python.exe is missing. Decode the bundle again.
  pause
  exit /b 1
)
echo.
echo   Hebrew Whisper - audio/video to Hebrew text
echo   ===========================================
echo.
if "%~1"=="" (
  echo   Tip: drag files or a folder onto TRANSCRIBE.bat.
  echo.
  set /p "HW_SRC=  File or folder: "
  call :one
) else (
  "%HW_PY%" -X utf8 "%HW_ROOT%app\transcribe.py" %*
)
echo.
pause
exit /b 0

:one
if not defined HW_SRC exit /b 0
set "HW_SRC=%HW_SRC:"=%"
"%HW_PY%" -X utf8 "%HW_ROOT%app\transcribe.py" "%HW_SRC%"
exit /b 0
