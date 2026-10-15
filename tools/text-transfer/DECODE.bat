@echo off
title Text transfer - decode
setlocal enableextensions

rem ===========================================================================================
rem  Double-click entry point on the FAR side of the transfer. Ships next to
rem  TextTransfer-Decode.ps1 and the TextTransfer-*.txt chunks, and works from wherever they
rem  were copied: every path is derived from this file's own location (%~dp0). pushd rather
rem  than `cd /d` so it also works from a network share or a redirected Desktop.
rem ===========================================================================================

pushd "%~dp0" || (
  echo Could not open "%~dp0".
  pause
  exit /b 1
)

echo.
echo   Text transfer - decode
echo   ======================
echo   Folder: %CD%
echo.

where powershell >nul 2>&1 || (
  echo   PowerShell was not found, which should not be possible on Windows 10 or 11.
  echo   Nothing has been changed.
  pause
  popd
  exit /b 1
)

rem The decoder travels beside the chunks; in the tool's own repo it lives in scripts\.
set "PS=%~dp0TextTransfer-Decode.ps1"
if not exist "%PS%" set "PS=%~dp0scripts\TextTransfer-Decode.ps1"
if not exist "%PS%" (
  echo   TextTransfer-Decode.ps1 is missing. It has to sit in this folder, next to the
  echo   TextTransfer-*.txt chunks. Copy it across and run this again.
  pause
  popd
  exit /b 1
)

rem -ExecutionPolicy Bypass is scoped to THIS run only and changes no machine setting.
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS%" %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo   Decoded. The original files are in the "decoded" folder.
) else (
  echo   Decoding stopped. Read the message above -- it names what to re-send.
)
echo.
pause
popd
exit /b %RC%
