@echo off
setlocal enableextensions
title Hebrew Whisper - back to the previous version
chcp 65001 >nul
rem Puts back the version that was installed before the last update (its backup is in
rem <Hebrew Whisper>\_updates). Drag the Hebrew Whisper folder onto it if not in C:\HebrewWhisper.

set "ROOT="
if not "%~1"=="" if exist "%~1\python\python.exe" set "ROOT=%~1"
if not defined ROOT if exist "C:\HebrewWhisper\python\python.exe" set "ROOT=C:\HebrewWhisper"
if not defined ROOT if exist "%SystemDrive%\HebrewWhisper\python\python.exe" set "ROOT=%SystemDrive%\HebrewWhisper"
if not defined ROOT (
  echo   Hebrew Whisper was not found. Drag its folder onto this file.
  pause
  exit /b 1
)
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
echo.
echo   Hebrew Whisper: %ROOT%
echo   Close the Hebrew Whisper window if it is open.
echo.
"%ROOT%\python\python.exe" -X utf8 "%~dp0apply_update.py" --restore --root "%ROOT%" --restart --wait 60
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo   OK - the previous version is back.) else (echo   FAILED - read the message above.)
echo.
pause
exit /b %RC%
