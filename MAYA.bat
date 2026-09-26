@echo off
setlocal
cd /d "%~dp0"

set "MAYA_PYTHON=%~dp0.maya-venv\Scripts\python.exe"
if not exist "%MAYA_PYTHON%" (
    echo Primo avvio: preparo ambiente M.A.Y.A...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1"
    if errorlevel 1 (
        echo Preparazione fallita.
        pause
        exit /b 1
    )
)

start "M.A.Y.A." /min "%MAYA_PYTHON%" "%~dp0main.py"
exit /b 0
