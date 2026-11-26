@echo off
setlocal enableextensions
title Hebrew Whisper - update
chcp 65001 >nul
rem Installs the update kit this file sits in. Double-click it, or drag the Hebrew Whisper
rem folder (the one with SELFTEST.bat) onto it if Hebrew Whisper is not in C:\HebrewWhisper.
rem Needed once for an install from before 1.1.0 (no update button yet); from 1.1.0 on the app
rem offers "Update and restart" by itself. Remembers this kit's folder as the updates folder.

set "ROOT="
if not "%~1"=="" (
  if exist "%~1\python\python.exe" set "ROOT=%~1"
  if exist "%~dp1python\python.exe" if /I "%~nx1"=="SELFTEST.bat" set "ROOT=%~dp1"
)
if not defined ROOT if exist "C:\HebrewWhisper\python\python.exe" set "ROOT=C:\HebrewWhisper"
if not defined ROOT if exist "%SystemDrive%\HebrewWhisper\python\python.exe" set "ROOT=%SystemDrive%\HebrewWhisper"
if not defined ROOT (
  echo.
  echo   Hebrew Whisper was not found in C:\HebrewWhisper.
  echo   Drag its folder ^(the one with SELFTEST.bat^) onto this file.
  echo.
  pause
  exit /b 1
)
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
echo.
echo   Hebrew Whisper: %ROOT%
echo   Close the Hebrew Whisper window if it is open.
echo.
"%ROOT%\python\python.exe" -X utf8 "%~dp0apply_update.py" --kit "%~dp0." --root "%ROOT%" --remember --restart --wait 60
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo   OK - Hebrew Whisper opens in the new version.) else (echo   FAILED - nothing was changed. Read the message above.)
echo.
pause
exit /b %RC%
