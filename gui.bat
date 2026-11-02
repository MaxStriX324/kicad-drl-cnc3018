@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title KiCad DRL to CNC3018 - GUI
set "PYTHONUTF8=1"
set "PYTHON_CMD="

py -3 -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if not errorlevel 1 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    python -c "import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo ERROR: Python 3.10+ with Tkinter not found.
    echo Run install.bat; use the official Python installer if Tkinter is absent.
    pause
    exit /b 1
)
%PYTHON_CMD% "%~dp0gui.py" %*
set "CODE=%errorlevel%"
if not "%CODE%"=="0" (
    echo GUI failed to start. Check messages above.
    pause
)
exit /b %CODE%
