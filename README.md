# M.A.Y.A. 🧠 — Multitask Advanced Yielding Assistant
 
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-black?style=for-the-badge&logo=ollama&logoColor=white)
![Arduino](https://img.shields.io/badge/Arduino-Hardware-00979D?style=for-the-badge&logo=arduino&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=for-the-badge)
![Stars](https://img.shields.io/github/stars/gabrielerossoni/maya-agent?style=for-the-badge&logo=github)
![Issues](https://img.shields.io/github/issues/gabrielerossoni/maya-agent?style=for-the-badge)
![Last Commit](https://img.shields.io/github/last-commit/gabrielerossoni/maya-agent?style=for-the-badge)
 
Sistema AI agentico locale, offline-first, costruito su **Ollama** + **FastAPI** con architettura **Planner → Executor → Validator** e dashboard WebSocket in tempo reale.
 
---
 
## Architettura
 
```
┌─────────────────────────────────────────────────────────────┐
│                        main.py (FastAPI)                    │
│   ┌──────────────┐   ┌────────────────┐   ┌─────────────┐  │
│   │  HTTP /      │   │  WS /ws        │   │  CLI stdin  │  │
│   └──────┬───────┘   └───────┬────────┘   └──────┬──────┘  │
│          └──────────────┬────┘                   │          │
│                         ▼                        │          │
│               ┌─────────────────┐                │          │
│               │   AgentCore     │◄───────────────┘          │
│               │  ┌───────────┐  │                           │
│               │  │  Planner  │  │  → automazioni keyword    │
│               │  │   (LLM)   │  │  → routing modello        │
│               │  └─────┬─────┘  │                           │
│               │  ┌─────▼─────┐  │                           │
│               │  │ Executor  │  │  → ToolManager            │
│               │  └─────┬─────┘  │                           │
│               │  ┌─────▼─────┐  │                           │
│               │  │ Validator │  │  → error check            │
│               │  └───────────┘  │                           │
│               └────────┬────────┘                           │
│                        │                                     │
│         ┌──────────────▼──────────────┐                     │
│         │         ToolManager         │                      │
│         │  arduino │ calendar │ weather│                     │
│         │  network │ trading  │ search │                     │
│         │  notes   │ timer    │ news   │                     │
│         │  spotify │ system   │ more.. │                     │
│         └─────────────────────────────┘                     │
│                                                              │
│   WebSocketManager ──► jarvis_dashboard.html (Chart.js)     │
│   MemoryManager    ──► data/memory.json                      │
│   DisplayTool      ──► ASCII terminal panel                  │
└─────────────────────────────────────────────────────────────┘
```
 
---
 
## Caratteristiche
 
- **100% Offline & Privato** — nessuna API key esterna, LLM locale via Ollama
- **Agentic Routing** — selezione automatica del modello in base alla complessità del task (ultra-fast / fast / balanced)
- **Pattern Planner → Executor → Validator** — pipeline strutturata con fallback parser keyword-based
- **Automazioni predefinite** — trigger su frasi chiave (`buonanotte`, `modalità film`, `modalità lavoro`) che attivano sequenze multi-tool
- **Tool System modulare** — 14 tool plug-in con interfaccia `initialize()` / `execute(action: dict)` uniforme
- **Controllo Hardware Arduino** — relay, LED, servo via PySerial con auto-discovery porta COM e fallback simulazione
- **Rete multi-PC** — invio comandi TCP a un secondo nodo con server incluso (`run_server()`)
- **Memoria persistente** — sliding window di 10 turni su `data/memory.json`
- **Dashboard WebSocket real-time** — CPU, RAM, log, controlli hardware; aggiornamento a 3 Hz via FastAPI + WS
- **Filler intelligente** — genera risposta di attesa con `llama3.2` mentre il modello lento elabora
- **Display ASCII** — pannello di stato animato su terminale separato (thread daemon)
---
 
## Stack Tecnologico
 
| Layer | Tecnologia |
|---|---|
| LLM Runtime | Ollama (llama3.2, phi4, mistral-small) |
| Backend API | FastAPI + Uvicorn |
| Real-time | WebSockets (fastapi native) |
| Hardware | PySerial + Arduino (C++) |
| Rete | socket TCP raw |
| Crypto/Stock | CoinGecko API + yfinance |
| Meteo | Open-Meteo API (geocoding + forecast) |
| News | feedparser (RSS ANSA) |
| Ricerca | DuckDuckGo Search (duckduckgo-search) |
| Wikipedia | wikipedia python SDK |
| Traduzione | deep-translator (Google backend) |
| Monitoring | psutil |
| Media | keyboard (media keys) + webbrowser |
| Frontend | Tailwind CDN + Chart.js + GSAP + Lucide |
| Persistenza | JSON locale (data/) |
 
---
 
## Struttura Repository
 
```
maya/
├── main.py                  # Entrypoint: FastAPI, lifecycle, CLI, WS, stats broadcaster
├── agent_core.py            # Planner/Executor/Validator, LLM routing, automazioni
├── tool_manager.py          # Registry e dispatcher di tutti i tool
├── memory_manager.py        # Sliding window memory, load/save JSON
├── websocket_manager.py     # Broadcast manager WebSocket
│
├── tools/
│   ├── arduino_tool.py      # Seriale USB → Arduino (auto-discovery + sim mode)
│   ├── network_tool.py      # TCP client + TCP server (secondo PC)
│   ├── system_tool.py       # OS commands (shutdown, browser, screenshot, volume)
│   ├── calendar_tool.py     # Calendario locale JSON (add/list/delete/next)
│   ├── weather_tool.py      # Open-Meteo geocoding + forecast
│   ├── news_tool.py         # RSS reader (ANSA default)
│   ├── wikipedia_tool.py    # Wikipedia summary (it)
│   ├── notes_tool.py        # Todo list e appunti JSON
│   ├── trading_tool.py      # CoinGecko (crypto) + yfinance (stocks) + TradingView
│   ├── timer_tool.py        # Timer asincrono (asyncio.create_task)
│   ├── translate_tool.py    # deep-translator (auto-detect source)
│   ├── search_tool.py       # DuckDuckGo web search (it-it, 3 risultati)
│   ├── spotify_tool.py      # Media keys: play/pause/next/prev + webbrowser
│   ├── sys_monitor_tool.py  # CPU % + RAM % via psutil
│   └── display_tool.py      # ASCII status panel (thread separato)
│
├── arduino/
│   └── jarvis_controller.ino  # Firmware Arduino: LED, relay, servo, serial protocol
│
├── static/
│   └── jarvis_dashboard.html  # SPA dashboard (Tailwind + Chart.js + GSAP)
│
├── data/                    # Runtime data (gitignored)
│   ├── memory.json
│   ├── calendar.json
│   └── notes.json
│
├── scratch/
│   └── verify_env.py        # Utility verifica env + import AgentCore
│
├── requirements.txt
├── .env.example
└── .gitignore
```
 
---
 
## Setup
 
### 1. Prerequisiti
 
- Python 3.10+
- [Ollama](https://ollama.com/) installato e in esecuzione (`ollama serve`)
- Arduino (opzionale — il sistema degrada in simulazione automaticamente)
### 2. Installazione
 
```bash
git clone https://github.com/tuo-username/maya-agent.git
cd maya-agent
pip install -r requirements.txt
```
 
### 3. Configurazione
 
```bash
cp .env.example .env
# Edita .env con i tuoi parametri
```
 
Variabili disponibili:
 
```env
# LLM
OLLAMA_HOST=127.0.0.1
MODEL_ULTRA_FAST=llama3.2      # task semplici / filler
MODEL_FAST=phi4                 # task medi
MODEL_BALANCED=mistral-small    # task complessi
 
# Hardware
ARDUINO_PORT=AUTO              # oppure COM3, /dev/ttyUSB0
ARDUINO_BAUD_RATE=9600
 
# Rete secondo PC
REMOTE_HOST=192.168.1.100
REMOTE_PORT=9999
 
# Tool defaults
DEFAULT_WEATHER_LOCATION=Roma
NEWS_FEED_URL=https://www.ansa.it/sito/ansait_rss.xml
 
# Personalità LLM (opzionale override)
SYSTEM_PROMPT_PERSONALITY=...
```
 
### 4. Download modelli Ollama
 
```bash
ollama pull llama3.2
ollama pull phi4
ollama pull mistral-small
```
 
### 5. Avvio
 
```bash
python main.py
```
 
Dashboard disponibile su: `http://127.0.0.1:8000`
 
---
 
## Protocollo Tool
 
Ogni tool implementa l'interfaccia:
 
```python
class MyTool:
    def initialize(self) -> None: ...
    def execute(self, action: dict) -> dict: ...
    # Per tool asincroni:
    async def execute(self, action: dict) -> dict: ...
```
 
Il `ToolManager` rileva automaticamente se `execute` è coroutine e lo awaita di conseguenza.
 
Response contract:
 
```json
{ "status": "ok" | "error" | "warning", "message": "..." }
```
 
---
 
## Formato JSON LLM
 
Il sistema prompt forza l'LLM a rispondere esclusivamente in questo schema:
 
```json
{
  "intent": "descrizione breve del task",
  "actions": [
    { "tool": "weather", "location": "Milano" },
    { "tool": "arduino", "command": "LIGHT_ON" }
  ],
  "reply": "Risposta naturale in italiano"
}
```
 
In caso di fallback (Ollama non disponibile), `AgentCore._fallback_parse()` gestisce le keyword più comuni senza LLM.
 
---
 
## Automazioni
 
Definite in `AUTOMATIONS` su `agent_core.py`. Trigger a keyword esatte nel testo utente.
 
| Trigger | Azioni |
|---|---|
| `buonanotte` | LIGHT_OFF → network GOODNIGHT → shutdown |
| `modalità lavoro` | LIGHT_ON → open_browser → network WORK_MODE |
| `modalità film` | RELAY_ON → LIGHT_OFF → open_browser |
 
Per aggiungere un'automazione:
 
```python
AUTOMATIONS["modalità gaming"] = [
    {"tool": "arduino", "command": "RELAY_ON"},
    {"tool": "system", "command": "open_browser"},
]
```
 
---
 
## Arduino — Protocollo Seriale
 
Baud: `9600` | Terminatore: `\n`
 
| Comando | Effetto | Risposta |
|---|---|---|
| `LIGHT_ON` | LED pin 13 HIGH | `OK:LIGHT_ON` |
| `LIGHT_OFF` | LED pin 13 LOW | `OK:LIGHT_OFF` |
| `RELAY_ON` | Relay pin 7 HIGH | `OK:RELAY_ON` |
| `RELAY_OFF` | Relay pin 7 LOW | `OK:RELAY_OFF` |
| `SERVO_OPEN` | Servo → 90° | `OK:SERVO_OPEN` |
| `SERVO_CLOSE` | Servo → 0° | `OK:SERVO_CLOSE` |
| `STATUS` | Report stato | `STATUS:LIGHT=ON,RELAY=OFF,SERVO=0` |
 
Senza Arduino connesso o senza `pyserial`, il sistema entra in **modalità simulazione** automaticamente — nessuna modifica al codice necessaria.
 
---
 
## Secondo PC — Server TCP
 
Sul secondo nodo, avviare il server incluso:
 
```bash
python -c "from tools.network_tool import run_server; run_server()"
```
 
Il server accetta payload JSON `{ "command": "...", "source": "jarvis" }` e risponde con `{ "status": "ok", "executed": "..." }`.
 
---
 
## WebSocket API
 
Il frontend si connette a `ws://127.0.0.1:8000/ws`.
 
Messaggi server → client:
 
```json
{ "type": "log",   "text": "...", "level": "ok|info|warn" }
{ "type": "stats", "neural_load": 12.4, "memory": 45.2, ... }
{ "type": "state", "led": "on", "relay": "off", "servo": "closed", ... }
```
 
Messaggi client → server:
 
```json
{ "type": "command", "text": "accendi la luce" }
```
 
---
 
## Aggiungere un Tool
 
1. Creare `tools/my_tool.py` con classe `MyTool` che implementa `initialize()` e `execute()`
2. Registrarlo in `tool_manager.py`:
   ```python
   from tools.my_tool import MyTool
   # in initialize():
   "my_tool": MyTool(),
   ```
3. Aggiungerlo al `SYSTEM_PROMPT` in `agent_core.py` nella sezione "Tool disponibili"
---
 
## Note Tecniche
 
- Il routing del modello in `_select_model()` è keyword-based sincrono — nessun overhead LLM per la selezione
- `_generate_filler()` usa sempre `llama3.2` indipendentemente dal modello selezionato, per garantire latenza bassa sulla risposta intermedia
- `stats_broadcaster()` gira a 0.33s (3 Hz) ma il grafico frontend aggiorna a frame rate nativo con `Chart.js update('none')`
- I tool informativi (weather, trading, search, ecc.) vengono eseguiti **dopo** che l'LLM ha già generato la `reply`, e il loro output viene concatenato — questo è intenzionale per separare la personalità della risposta dai dati grezzi
- `memory_manager.py` mantiene al massimo `MAX_TURNS = 10` turni in RAM e inietta solo gli ultimi 6 nel prompt LLM
---
 
## .gitignore — Cosa viene escluso
 
```
data/          # memory.json, calendar.json, notes.json
.env           # credenziali e configurazioni locali
.venv/         # virtualenv
__pycache__/
.vscode/
```
 
---
 
## Roadmap
 
- [X] Voice I/O (Whisper local + TTS)
- [ ] Google Calendar sync (oauth2 già predisposto in requirements)
- [ ] Streaming LLM response via WebSocket (token-by-token)
- [ ] Plugin system dinamico (hot-reload tool senza restart)
- [ ] Multi-room Arduino (broker MQTT)
- [ ] Dashboard mobile (PWA)
---
 
## Autori
 
Progetto sviluppato da studenti dell'**ITIS di Crema**.
 
| | |
|---|---|
| **Gabriele Rossoni** | Architettura sistema, backend Python, integrazione LLM, hardware Arduino |
| **Marcello Patrini** | Co-sviluppatore, testing, integrazione tool |
 
[![GitHub gabrielerossoni](https://img.shields.io/badge/GitHub-gabrielerossoni-181717?style=flat-square&logo=github)](https://github.com/gabrielerossoni)
 
---
 
<p align="center">Fatto dall'<strong>ITIS di Crema</strong></p>