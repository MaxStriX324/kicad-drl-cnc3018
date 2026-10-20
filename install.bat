@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 goto success
where python >nul 2>&1
if not errorlevel 1 goto success

echo Python 3 not found. Attempting Python 3 installation with winget.
where winget >nul 2>&1
if errorlevel 1 (
    echo winget is unavailable. Install Python from https://www.python.org/downloads/
    echo Enable 'Add Python to PATH', reopen the terminal, then run start.bat.
    pause
    exit /b 1
)
winget install --id Python.Python.3.13 --exact --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo Installation failed. Install Python manually and retry.
    pause
    exit /b 1
)
echo Python installed. Close/reopen your terminal before running start.bat.
pause
exit /b 0

:success
echo Python detected. No additional packages are required.
pause
exit /b 0
