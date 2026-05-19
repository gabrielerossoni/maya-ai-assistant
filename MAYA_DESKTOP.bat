@echo off
if not "%1"=="-hidden" (
    powershell -Command "Start-Process -FilePath '%~f0' -ArgumentList '-hidden' -WindowStyle Hidden"
    exit /b
)
title MAYA - Smart Order Launcher
cls

if not exist "node_modules\" (
    npm install --silent
)

set MAYA_SKIP_BROWSER_OPEN=1
npm start --silent
