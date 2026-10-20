@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
title KiCad DRL to GRBL TAP - CNC3018
set "SCRIPT=%~dp0drl_to_tap.py"

where py >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Python not found. Run install.bat first.
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

if "%~1"=="" (
    echo Drag a KiCad .drl file onto start.bat or enter full path below.
    set /p "DRL=DRL file: "
) else (
    set "DRL=%~1"
)
if not defined DRL (
    echo No file selected.
    pause
    exit /b 1
)

rem User may add extra CLI options after filename, e.g. --skip-slots --z-drill -1.8
%PYTHON% "%SCRIPT%" "%DRL%" %2 %3 %4 %5 %6 %7 %8 %9
set "CODE=%errorlevel%"
if not "%CODE%"=="0" echo Conversion failed. See message above.
pause
exit /b %CODE%
