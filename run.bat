@echo off
rem Launch Ventris on Windows. Usage: run.bat [file]
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -m ventris %*
) else (
  py -3 -m ventris %*
)
