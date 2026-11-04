@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title KiCad DRL to GRBL TAP - CNC3018
set "PYTHONUTF8=1"
set "PYTHON_CMD="

rem Validate the interpreter, not just the presence of a Windows Store alias.
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    if exist "%LocalAppData%\Programs\Python\Python314\python.exe" (
        "%LocalAppData%\Programs\Python\Python314\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python314\python.exe"
    )
)
if not defined PYTHON_CMD (
    if exist "%LocalAppData%\Programs\Python\Python313\python.exe" (
        "%LocalAppData%\Programs\Python\Python313\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=%LocalAppData%\Programs\Python\Python313\python.exe"
    )
)
if not defined PYTHON_CMD (
    echo ERROR: Python 3.10+ not found or cannot be started.
    echo Run install.bat and reopen this window.
    pause
    exit /b 1
)

rem No filename prompt: without arguments, scan this folder and input/ automatically.
rem Drag one or more DRL files or directories onto this launcher if preferred.
call :run_python "%~dp0auto_convert.py" %*
set "CODE=%errorlevel%"
if not "%CODE%"=="0" echo Check conversion_report.txt for details.
if "%~1"=="" pause
exit /b %CODE%

:run_python
if /i "%PYTHON_CMD%"=="py -3" (py -3 %*) else ("%PYTHON_CMD%" %*)
exit /b %errorlevel%
