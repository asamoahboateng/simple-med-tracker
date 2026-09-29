@echo off
REM Start MedTracker using the project's virtual environment (no activation needed).
REM Pass --demo to use the separate demo database:  run.bat --demo
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo The virtual environment is missing. Run setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" main.py %*
