# M.A.Y.A.

M.A.Y.A. è un assistente locale orientato all'uso quotidiano: espone una dashboard FastAPI, coordina modelli locali o cloud, usa strumenti applicativi e mantiene memoria e automazioni persistenti.

Il progetto è software-first. Le integrazioni domotiche passano da MQTT e restano disaccoppiate dai dispositivi fisici: il core non dipende da una scheda, da una porta seriale o da un firmware specifico.

## Funzioni principali

- orchestrazione LLM con routing tra conversazione, ragionamento, coding e domotica;
- strumenti per meteo, notizie, calendario, ricerca, sistema, Spotify e MQTT;
- dashboard web e aggiornamenti real-time via WebSocket;
- memoria strutturata e semantica;
- scene e automazioni event-driven con retry, priorità e cooldown;
- input e output vocali opzionali;
- funzionamento locale tramite Ollama oppure cloud tramite Groq.

## Architettura

```text
Dashboard / Voice / API
          |
       FastAPI
          |
      AgentCore
      /   |   \
   Tools Memory Automations
     |
 MQTT e servizi applicativi
```

`AgentCore` interpreta la richiesta, applica i percorsi diretti quando non serve un modello e usa un ciclo ReAct limitato per le richieste che richiedono strumenti. `ToolManager` costituisce il confine tra ragionamento e integrazioni. `AutomationEngine` esegue scene generiche senza conoscere l'hardware sottostante.

## Requisiti

- Python 3.11 o successivo;
- Ollama locale oppure credenziali Groq;
- broker MQTT solo se si usano funzioni domotiche;
- credenziali dedicate per le integrazioni opzionali.

## Avvio

Su Windows, dopo il primo setup, fai doppio clic su `MAYA.bat`: prepara `.maya-venv` se manca e avvia M.A.Y.A. in background.

```powershell
./scripts/bootstrap.ps1
Copy-Item .env.example .env
./MAYA.bat
```

La dashboard è disponibile all'indirizzo stampato all'avvio. Le variabili principali sono documentate in `.env.example`.

## MQTT

Il tool MQTT pubblica comandi sul topic `maya/rooms/<room>/cmd` e riceve stato e telemetria dai topic corrispondenti. Il payload applicativo è JSON e viene validato prima della pubblicazione. La configurazione minima è:

```dotenv
MQTT_BROKER=localhost
MQTT_PORT=1883
MQTT_DEFAULT_ROOM=studio
MQTT_COMMAND_TOKEN=
```

Il broker deve applicare autenticazione, ACL per topic e TLS quando il traffico esce dalla macchina o dalla LAN fidata.

## Test e qualità

```powershell
python -m pytest -q
python -m graphify update .
```

La knowledge graph del repository è salvata in `graphify-out/`. Per analizzare relazioni e responsabilità usare `graphify query`, `graphify explain` e `graphify path`.

## Licenza

Vedi [LICENSE](LICENSE).
