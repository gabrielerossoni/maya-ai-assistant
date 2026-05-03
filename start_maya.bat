@echo off
title M.A.Y.A. - Neural Startup
cls

echo ===================================================
echo           M.A.Y.A. SYSTEM INITIALIZATION
echo ===================================================
echo.

:: 0. Pulizia Porta 8000 (FastAPI)
echo [1/4] Controllo porta 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do taskkill /f /pid %%a >nul 2>&1
echo [-] Porta 8000 pronta.

:: 1. Avvio/Verifica Ollama (porta API 11434)
echo [2/4] Verifica motore AI (Ollama)...
set "OLLAMA_EXE=ollama"
where ollama >nul 2>&1
if %ERRORLEVEL% neq 0 (
  if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" (
    set "OLLAMA_EXE=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
  ) else (
    echo [ERR] Ollama non trovato. Installa da https://ollama.com
    pause
    exit /b 1
  )
)

netstat -an | findstr :11434 | findstr LISTENING >nul
if %ERRORLEVEL% == 0 goto ollama_ready

echo [+] Avvio di Ollama in corso...
start "" /B "%OLLAMA_EXE%" serve
echo [!] In attesa che il motore AI risponda sulla porta 11434...
set retry=0

:wait_ollama
timeout /t 2 >nul
netstat -an | findstr :11434 | findstr LISTENING >nul
if %ERRORLEVEL% == 0 goto ollama_ready

set /a retry=%retry%+1
if %retry% geq 20 goto ollama_error
goto wait_ollama

:ollama_ready
echo [-] Ollama e' attivo e pronto.
goto next_step

:ollama_error
echo [ERR] Ollama non risponde dopo ~40 secondi. Avvia l'app Ollama dal menu Start e riprova.
pause
exit /b

:next_step
:: 2. Verifica Dipendenze Python
echo [3/4] Verifica moduli di sistema...
pip install -r requirements.txt >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [!] Errore nell'installazione delle dipendenze.
    pause
    exit /b
)
echo [-] Moduli OK.

:: 3. Avvio Nucleo MAYA
echo [4/4] Inizializzazione Nucleo...
echo.
echo ---------------------------------------------------
echo       M.A.Y.A. ONLINE - INTERFACE LOADING...
echo ---------------------------------------------------
echo.

python main.py

pause
