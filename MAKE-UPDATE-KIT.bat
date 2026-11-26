@echo off
setlocal enableextensions
title Hebrew Whisper - build an update kit
rem Run on blackberry (internet), after git pull. Builds only what changed since the version on
rem the offline PC. Output: build\kit-<version>-text\  -> copy everything there to the stick.
rem The offline PC must have the version this kit is built against (the newest one built here
rem before). Other base: MAKE-UPDATE-KIT.bat -Base 1.1.0
set "HW_PS=%~dp0scripts\build-update-kit.ps1"
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%HW_PS%" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo   OK) else (echo   FAILED - read the message above)
pause
exit /b %RC%
