@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"

call :check_python
if not errorlevel 1 goto success

echo Python 3.10+ is missing or cannot be started.
where winget >nul 2>&1
if errorlevel 1 (
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo Enable Add python.exe to PATH, then run install.bat again.
    pause
    exit /b 1
)
echo Installing Python with winget...
winget install --id Python.Python.3.13 --exact --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo Python installation failed. Check winget output above.
    pause
    exit /b 1
)
call :check_python
if errorlevel 1 (
    echo Python was installed but is not available in this process yet.
    echo Open a new terminal and run install.bat again.
    pause
    exit /b 1
)

:success
if not exist "%~dp0input" mkdir "%~dp0input"
if not exist "%~dp0auto_convert.py" (
    echo ERROR: auto_convert.py is missing. Download the complete repository ZIP.
    pause
    exit /b 1
)
echo Python verified. No external Python packages are required.
echo Put KiCad .drl files beside start.bat or into the input folder.
echo Double-click start.bat to convert automatically, or gui.bat for the graphical window.
if not exist "%~dp0settings.json" (
    echo Note: settings.json will be created when you save settings in the GUI.
)
call :check_tk
if errorlevel 1 (
    echo WARNING: Tkinter is missing. start.bat will work, but gui.bat requires Tkinter.
    echo Install Python from python.org with Tcl/Tk support if you need the GUI.
) else (
    echo Tkinter verified. The graphical interface can be launched with gui.bat.
)
pause
exit /b 0

:check_python
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 exit /b 0
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 exit /b 0
exit /b 1

:check_tk
py -3 -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 exit /b 0
python -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 exit /b 0
exit /b 1
