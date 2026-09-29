@echo off
REM MedTracker one-step setup for Windows.
REM Creates .venv in this folder, upgrades pip and installs all requirements.
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo Python 3.10 or newer was not found. Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo Python 3.10 or newer is required.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv ...
    %PY% -m venv .venv
    if errorlevel 1 goto :failed
)

echo Upgrading pip ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :failed

echo Installing requirements ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt -r requirements-dev.txt
if errorlevel 1 goto :failed

echo.
echo Setup complete.
echo   Start the app: double-click run.bat (or run.bat --demo)
echo   Activate the venv (Command Prompt): .venv\Scripts\activate.bat
pause
exit /b 0

:failed
echo.
echo Setup FAILED. Read the messages above for the reason.
pause
exit /b 1
