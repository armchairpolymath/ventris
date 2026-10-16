@echo off
rem Launch G-code Analyzer on Windows. Usage: run.bat [file]
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m gcode_analyzer %*
) else (
  py -3 -m gcode_analyzer %*
)
