@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Install the project dependencies first. See README.md.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "client\src\main.py" %*
if errorlevel 1 pause
