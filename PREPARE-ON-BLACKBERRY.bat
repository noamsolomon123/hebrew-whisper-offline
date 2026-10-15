@echo off
setlocal enableextensions
title Hebrew Whisper - build offline bundle
rem Run on blackberry (internet). Downloads ~5 GB, needs ~15 GB free.
rem Output: build\HebrewWhisper-text\  -> copy everything there to the stick.
set "HW_PS=%~dp0scripts\prepare.ps1"
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%HW_PS%" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo   OK) else (echo   FAILED - read the message above)
pause
exit /b %RC%
