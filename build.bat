@echo off
REM Build MedTracker for Windows (one step): a folder, plus an installer if Inno Setup is installed.
REM   Double-click build.bat, or run it in Command Prompt / PowerShell.
REM Output: dist\MedTracker\MedTracker.exe  and (with Inno Setup 6) dist\MedTracker-Setup-<version>.exe
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
"%PY%" scripts\make_cloud_keys.py
"%PY%" -m PyInstaller medtracker.spec --noconfirm --clean
if errorlevel 1 goto :failed

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" (
    echo ==^> Making the installer
    "%ISCC%" "/DMyAppVersion=%VERSION%" installer\medtracker.iss
    if errorlevel 1 goto :failed
)

echo.
echo Done. Your program is in the dist folder:
echo   dist\MedTracker\MedTracker.exe   (keep the whole MedTracker folder together)
if exist "dist\MedTracker-Setup-%VERSION%.exe" echo   dist\MedTracker-Setup-%VERSION%.exe   (the installer to share; installed copies can update themselves)
if not exist "dist\MedTracker-Setup-%VERSION%.exe" echo   (Install Inno Setup 6 from https://jrsoftware.org/isinfo.php to also make an installer.)
echo If Windows SmartScreen warns you, click "More info" then "Run anyway".
pause
exit /b 0

:failed
echo.
echo Build FAILED. Read the messages above for the reason.
pause
exit /b 1
