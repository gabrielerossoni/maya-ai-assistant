"""
agent_core.py - Cuore dell'agente Jarvis
Gestisce: LLM (Ollama), Planner, Executor, Validator
"""

import os
import json
import re
import random
import ollama
import asyncio
from tool_manager import ToolManager
from memory_manager import MemoryManager
from dotenv import load_dotenv

# Carica variabili d'ambiente da .env
load_dotenv()

# Forza l'utilizzo di IPv4 per evitare problemi con localhost su Windows
os.environ["OLLAMA_HOST"] = os.getenv("OLLAMA_HOST", "127.0.0.1")

# ──────────────────────────────────────────────
# CONFIGURAZIONE
# ──────────────────────────────────────────────
MODELS = {
    "ultra-fast": os.getenv("MODEL_ULTRA_FAST", "llama3.2"),
    "fast": os.getenv("MODEL_FAST", "phi4"),
    "balanced": os.getenv("MODEL_BALANCED", "mistral-small"),
}

ACTIVE_MODEL = MODELS["ultra-fast"]

# Carica il prompt dal .env se disponibile, altrimenti usa il default
DEFAULT_PROMPT = """Sei MAYA (Multitask Advanced Yielding Assistant), un assistente AI agentico evoluto.
Il tuo compito è aiutare l'utente gestendo la casa, cercando informazioni e fornendo dati in tempo reale.

REGOLE DI COMPORTAMENTO:
1. TOOL USAGE: Usa i tool SOLO se strettamente necessario per rispondere. Se l'utente ti saluta o fa chiacchiere, rispondi normalmente senza attivare tool a caso.
2. PERSONALITÀ: Sei sicura di te, un po' distaccata ma impeccabile nel servizio. Niente emoji eccessive, sii professionale e "tough".
3. FORMATO JSON (OBBLIGATORIO): Rispondi ESCLUSIVAMENTE con un oggetto JSON valido. È CRITICO che la chiave "reply" contenga la tua risposta completa per l'utente.
Struttura:
{
  "intent": "cosa vuole l'utente",
  "actions": [{"tool": "nome_tool", "parametro": "valore"}],
  "reply": "Tua risposta discorsiva e naturale in italiano"
}
SE NON HAI BISOGNO DI TOOL, lascia "actions" come lista vuota [].
NON aggiungere testo fuori dal JSON.
NON inventare dati: se usi un tool informativo, scrivi nella reply che stai controllando.

Tool disponibili:
- arduino: comandi hardware (LIGHT_ON, LIGHT_OFF, SERVO_OPEN, SERVO_CLOSE, RELAY_ON, RELAY_OFF)
- calendar: gestione eventi (action: add/list/delete, title, time "YYYY-MM-DD HH:MM")
- network: invia comandi al secondo PC (qualsiasi stringa)
- system: comandi OS (shutdown, open_browser, screenshot)
- weather: meteo (location)
- news: ultime notizie (limit)
- wikipedia: ricerca concetti (query)
- notes: liste e appunti (operation: add/remove/list, item, category: todo/spesa)
- trading: criptovalute e azioni (operation: price/chart, symbol, asset_type: crypto/stock)
- timer: sveglie (minutes, seconds, message)
- translate: traduci testo (text, target: es 'en', 'es')
- search: ricerca web (query)
- spotify: controllo Spotify reale (command: play_pause/play/pause/next/prev/current/volume_up/volume_down/volume/search, "query" per cercare brano, "level" 0-100 per volume)
- sys_monitor: statistiche cpu/ram
- none: risposta solo testuale

REGOLE CRITICHE:
1. NON RIFIUTARE MAI: Hai accesso a internet tramite i tool. Se l'utente chiede prezzi, meteo o notizie, usa i tool dedicati.
2. FORMATO: Rispondi SOLO con il JSON, nessun altro testo.
3. Se l'utente chiede il valore di una moneta, usa sempre 'trading' con operation 'price'.
4. Se usi un tool informativo (trading, weather, search, news), nella tua "reply" NON inventare MAI dati o cifre. Dì solo che stai recuperando le informazioni (es: "Certamente, controllo subito..."). I dati reali verranno aggiunti automaticamente dopo.
"""

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT_PERSONALITY", DEFAULT_PROMPT)

# Messaggi di filler per il feedback durante l'elaborazione (zero latenza aggiuntiva)
FILLER_MESSAGES = [
    "Certamente, recupero i dati...",
    "Un attimo, sto elaborando...",
    "Controllo subito...",
    "Accesso ai dati in corso...",
    "Elaborazione in corso...",
]


# ──────────────────────────────────────────────
# AUTOMAZIONI PREDEFINITE
# ──────────────────────────────────────────────
AUTOMATIONS = {
    "buonanotte": [
        {"tool": "arduino", "command": "LIGHT_OFF"},
        {"tool": "network", "message": "GOODNIGHT"},
        {"tool": "system", "command": "shutdown"},
    ],
    "modalità lavoro": [
        {"tool": "arduino", "command": "LIGHT_ON"},
        {"tool": "system", "command": "open_browser"},
        {"tool": "network", "message": "WORK_MODE"},
    ],
    "modalità film": [
        {"tool": "arduino", "command": "RELAY_ON"},
        {"tool": "arduino", "command": "LIGHT_OFF"},
        {"tool": "system", "command": "open_browser"},
    ],
}


class AgentCore:
    """
    Cuore del sistema agentico.
    Implementa il pattern Planner → Executor → Validator.
    """

    def __init__(self):
        self.tool_manager = ToolManager()
        self.memory = MemoryManager()
        self.conversation_history = []

    async def initialize(self):
        """Inizializza tutti i componenti."""
        print("[AGENT] Inizializzazione tool manager...")
        self.tool_manager.initialize()
        print("[AGENT] Caricamento memoria conversazioni...")
        self.memory.load()
        print("[AGENT] AgentCore pronto.\n")

    # ── FASE 1: PLANNER ──────────────────────────────────
    def _check_automation(self, user_input: str) -> list | None:
        """Controlla se l'input corrisponde a un'automazione predefinita."""
        lower = user_input.lower()
        for keyword, actions in AUTOMATIONS.items():
            if keyword in lower:
                print(f"[PLANNER] Automazione rilevata: '{keyword}'")
                return actions
        return None

    def _select_model(self, user_input: str) -> str:
        """
        Seleziona il modello in base alla complessità della query.
        - balanced (mistral-small): compiti cognitivi pesanti (analisi, riassunti, Wikipedia)
        - fast (phi4): tool informativi veloci (prezzo, meteo, notizie)
        - ultra-fast (llama3.2): comandi rapidi e conversazione
        """
        lower = user_input.lower()
        
        # Compiti cognitivi pesanti → mistral-small (balanced)
        heavy_keywords = [
            "spiega", "riassumi", "analizza", "significato", 
            "wikipedia", "traduci", "background", "storia", "origine"
        ]
        
        # Tool informativi veloci → phi4 (fast)
        fast_keywords = [
            "prezzo", "meteo", "bitcoin", "btc", "eth", "notizie", 
            "vale", "crypto", "trading", "azioni", "cerca", "news"
        ]
        
        if any(k in lower for k in heavy_keywords):
            return "balanced"  # mistral-small per compiti cognitivi
        if any(k in lower for k in fast_keywords) or len(user_input.split()) > 8:
            return "fast"  # phi4 per tool informativi
        return "ultra-fast"  # llama3.2 per comandi rapidi

    def _clean_json(self, text: str) -> dict:
        """
        Pulisce il testo dalla formattazione markdown (code fences)
        e ritorna un JSON valido. Fallback a _fallback_parse se parse fallisce.
        """
        # Rimuovi markdown code fences
        text = re.sub(r"```(?:json)?\s*", "", text).strip()
        # Estrai il primo oggetto JSON completo
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            text = match.group(0)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return self._fallback_parse(text)

    async def _call_llm(self, user_input: str, progress_cb=None) -> dict:
        """Chiama Ollama e ottieni JSON strutturato."""
        # Aggiungi contesto dalla memoria (retrieval semantico)
        context = await self.memory.get_context(query=user_input, top_k=5)
        prompt = f"{context}\nUtente: {user_input}"

        model_type = self._select_model(user_input)
        model_name = MODELS[model_type]
        print(f"[ROUTER] Modello selezionato: {model_name} ({model_type})")

        if model_type in ("fast", "balanced") and progress_cb:
            await progress_cb(random.choice(FILLER_MESSAGES))

        try:
            client = ollama.AsyncClient()
            response = await client.generate(
                model=model_name,
                system=SYSTEM_PROMPT,
                prompt=prompt,
                format="json",
                stream=False,
                options={"temperature": 0.4} # Rende l'output più prevedibile
            )

            text = response.get("response", "{}")
            result = self._clean_json(text)
            
            # Se l'LLM ha risposto ma manca la chiave reply, proviamo a recuperare
            if "reply" not in result and "response" in result:
                result["reply"] = result["response"]
            
            return result

        except Exception as e:
            print(f"[LLM] Errore di comunicazione con Ollama: {e}")
            print("[LLM] Assicurati che Ollama sia in esecuzione ('ollama serve').")
            return self._fallback_parse(user_input)

    def _fallback_parse(self, user_input: str) -> dict:
        """
        Parser di fallback per quando Ollama non è disponibile.
        Regole semplici basate su keyword.
        """
        lower = user_input.lower()
        actions = []
        reply = "Comando eseguito."

        if "accendi" in lower and ("luce" in lower or "led" in lower):
            actions.append({"tool": "arduino", "command": "LIGHT_ON"})
            reply = "Luce accesa!"
        elif "spegni" in lower and ("luce" in lower or "led" in lower):
            actions.append({"tool": "arduino", "command": "LIGHT_OFF"})
            reply = "Luce spenta!"
        elif "apri" in lower and "servo" in lower:
            actions.append({"tool": "arduino", "command": "SERVO_OPEN"})
            reply = "Servo aperto!"
        elif "aggiungi" in lower or "evento" in lower or "riunione" in lower:
            actions.append(
                {
                    "tool": "calendar",
                    "action": "add",
                    "title": user_input,
                    "time": "2026-04-26 12:00",
                }
            )
            reply = "Evento aggiunto al calendario."
        elif "calendario" in lower or "eventi" in lower:
            actions.append({"tool": "calendar", "action": "list"})
            reply = "Ecco i tuoi prossimi eventi."
        else:
            actions.append({"tool": "none", "response": user_input})
            reply = "Non ho Ollama attivo. Comando non riconosciuto."

        return {"intent": lower[:30], "actions": actions, "reply": reply}

    # ── FASE 2: EXECUTOR ─────────────────────────────────
    async def _execute_actions(self, actions: list) -> list:
        """Esegui ogni azione tramite il ToolManager."""
        results = []
        for action in actions:
            tool_name = action.get("tool", "none")
            print(f"[EXECUTOR] Eseguo tool: {tool_name} → {action}")
            result = await self.tool_manager.execute(action)
            results.append({"tool": tool_name, "result": result})
            print(f"[EXECUTOR] Risultato: {result}")
        return results

    # ── FASE 3: VALIDATOR ────────────────────────────────
    def _validate_results(self, results: list) -> bool:
        """Controlla che le azioni siano andate a buon fine."""
        for r in results:
            if r.get("result", {}).get("status") == "error":
                print(f"[VALIDATOR] Errore in tool {r['tool']}: {r['result']}")
                return False
        return True

    # ── PROCESSO PRINCIPALE ──────────────────────────────
    async def process(self, user_input: str, progress_cb=None) -> str:
        """Pipeline completa: Planner → Executor → Validator → Risposta."""

        # Salva input nella memoria (con embedding semantico)
        await self.memory.add_turn("user", user_input)

        # 1. PLANNER - controlla automazioni
        auto_actions = self._check_automation(user_input)
        if auto_actions:
            plan = {
                "intent": "automazione",
                "actions": auto_actions,
                "reply": f"Automazione '{user_input}' attivata!",
            }
        else:
            # 1b. PLANNER - chiedi all'LLM
            print("[PLANNER] Consultando LLM...")
            plan = await self._call_llm(user_input, progress_cb)

        intent = plan.get("intent", "conversazione")
        actions = plan.get("actions", [])
        reply = plan.get("reply")

        # Se l'LLM non ha fornito una risposta testuale, generiamone una di emergenza
        if not reply:
            if actions:
                reply = "Ho eseguito le azioni richieste."
            else:
                reply = "Mi dispiace, non sono riuscita a generare una risposta valida. Puoi ripetere?"

        print(f"[PLANNER] Intent: {intent} | Azioni: {len(actions)}")

        # 2. EXECUTOR
        results = await self._execute_actions(actions)

        # Integra i risultati dei tool informativi nel reply finale
        info_messages = []
        for res in results:
            if res["tool"] not in ["none", "arduino", "system"]:
                msg = res.get("result", {}).get("message")
                if msg and res.get("result", {}).get("status") == "ok":
                    info_messages.append(msg)

        if info_messages:
            # Mantieni la personalità del chatbot aggiungendo i dati in coda alla sua risposta
            reply = f"{reply}\n\n{ ' | '.join(info_messages) }"

        # 3. VALIDATOR
        ok = self._validate_results(results)
        if not ok:
            reply += " (Attenzione: alcune azioni potrebbero non essere riuscite.)"

        # Salva risposta nella memoria (con embedding semantico)
        await self.memory.add_turn("jarvis", reply)

        return reply
