# J.A.R.V.I.S. 🧠 - Sistema Agentico Locale

Un assistente AI "offline-first" scritto in Python, basato su **Ollama** e architettura multi-agente, dotato di una bellissima interfaccia Dashboard WebSocket in tempo reale.

## 🌟 Caratteristiche

- **100% Offline & Privato**: Nessuna API key esterna necessaria. I modelli girano in locale sul tuo PC tramite Ollama.
- **Agentic Routing**: Jarvis decide autonomamente quale modello utilizzare (es. `phi4` per esecuzione rapida di comandi hardware, `mistral-small` per compiti logici complessi).
- **Controllo Hardware**: Integra il controllo simulato e reale di Arduino (relè, LED, servo motori) tramite PySerial.
- **Memoria a Breve Termine**: Ricorda il contesto degli ultimi messaggi per un'esperienza di conversazione fluida, salvando tutto in `data/memory.json`.
- **Dashboard Web in Tempo Reale**: Interfaccia HTML/JS connessa tramite FastAPI e WebSockets. Mostra latenza LLM, contatore comandi, stato della memoria e controlli hardware aggiornati istantaneamente.
- **Formattazione del Codice Automatica**: Configurato per utilizzare Black Formatter tramite VS Code (`.vscode/settings.json`).

## 🛠️ Tecnologie

- Python 3.10+
- **FastAPI** + **Uvicorn** (Server & WebSockets)
- **Ollama** Python SDK
- **PySerial** (per Arduino)

## 🚀 Setup e Installazione

### 1. Requisiti di base

Assicurati di avere installato:

- [Python 3.10+](https://www.python.org/downloads/)
- [Ollama](https://ollama.com/)

### 2. Clona il Repository e installa le dipendenze

```bash
git clone https://github.com/tuo-username/jarvis-local-agent.git
cd jarvis-local-agent
pip install -r requirements.txt
```

### 3. Scarica i modelli in locale (tramite Ollama)

Di default Jarvis si aspetta che tu abbia installato i modelli definiti in `agent_core.py`. Ad esempio:

```bash
ollama pull phi4
ollama pull mistral-small
```

### 4. Avvia Jarvis

```bash
python main.py
```

Il terminale diventerà il tuo centro di comando CLI, e contemporaneamente si aprirà la Dashboard HTML nel tuo browser (`http://127.0.0.1:8000`). Entrambi sono sincronizzati in tempo reale!

## 📁 Struttura del Progetto

- `main.py`: Punto d'ingresso, server FastAPI e loop CLI.
- `agent_core.py`: Cervello (LLM logic, intent routing).
- `websocket_manager.py`: Sincronizzazione in tempo reale frontend/backend.
- `memory_manager.py`: Gestione storia conversazioni.
- `tools/`: Moduli per interazione col mondo esterno (display_tool, arduino_tool, ecc.).
- `static/`: Contiene la UI `jarvis_dashboard.html`.

## ⚠️ Avvertenze (.gitignore)

La cartella `data/` contenente `memory.json` è ignorata di default per evitare di caricare dati personali di conversazione su GitHub. Anche cartelle come `__pycache__` o `.venv` sono ignorate.

## 🤖 Modalità Sviluppo (Arduino)

Se non hai un Arduino connesso, il sistema rileverà automaticamente la mancanza di `pyserial` o della porta COM e degraderà elegantemente in **Modalità Simulazione**, mostrandoti i risultati dei comandi a schermo e aggiornando l'interfaccia UI.
