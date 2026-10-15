@echo off
setlocal enableextensions
rem Opens the drag-and-drop transcription page in the browser. No console stays open;
rem the program closes itself a minute after the browser tab is closed.
set "HW_ROOT=%~dp0"
if not exist "%HW_ROOT%python\pythonw.exe" (
  echo   python\pythonw.exe is missing. Extract the bundle again.
  pause
  exit /b 1
)
start "" "%HW_ROOT%python\pythonw.exe" -X utf8 "%HW_ROOT%app\server.py"
exit /b 0
