@echo off
REM === MAYA SMART ORDER LAUNCHER ===

REM 1. Controlla Node modules
if not exist "node_modules\" (
    echo [LAUNCHER] Node modules mancanti. Installazione in corso...
    npm install
)

REM 2. Avvia MAYA via Electron (che a sua volta avvierà main.py)
echo [LAUNCHER] Avvio interfaccia desktop...
npm start
