@echo off
REM Build MedTracker.exe for Windows (one step).
REM   Double-click build.bat, or run it in Command Prompt / PowerShell.
REM Output: dist\MedTracker.exe  and  dist\MedTracker-<version>-Windows.exe
REM Uses only the project's .venv (run setup.bat first). Tests run before building.
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo The virtual environment is missing. Run setup.bat first.
    pause
    exit /b 1
)
for /f "usebackq delims=" %%v in (`%PY% -c "import config; print(config.APP_VERSION)"`) do set "VERSION=%%v"

echo ==^> Running tests
"%PY%" -m pytest
if errorlevel 1 goto :failed

echo ==^> Building MedTracker %VERSION% with PyInstaller
"%PY%" -m PyInstaller medtracker.spec --noconfirm --clean
if errorlevel 1 goto :failed

copy /y "dist\MedTracker.exe" "dist\MedTracker-%VERSION%-Windows.exe" >nul

echo.
echo Done. Your program is in the dist folder:
echo   dist\MedTracker.exe
echo   dist\MedTracker-%VERSION%-Windows.exe   (same file, with the version in the name, to share)
echo If Windows SmartScreen warns you, click "More info" then "Run anyway".
pause
exit /b 0

:failed
echo.
echo Build FAILED. Read the messages above for the reason.
pause
exit /b 1
