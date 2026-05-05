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
from .tool_manager import ToolManager
from .memory_manager import MemoryManager
from dotenv import load_dotenv

# Carica variabili d'ambiente da .env
load_dotenv()

# Forza l'utilizzo di IPv4 per evitare problemi con localhost su Windows
os.environ["OLLAMA_HOST"] = os.getenv("OLLAMA_HOST", "127.0.0.1")

# ──────────────────────────────────────────────
# CONFIGURAZIONE
# ──────────────────────────────────────────────
MODELS = {
    "router": os.getenv("MODEL_ROUTER", "llama3.2:1b"),
    "domotic": os.getenv("MODEL_DOMOTIC", "phi4"),
    "reasoning": os.getenv("MODEL_REASONING", "mistral-small"),
    "chitchat": os.getenv("MODEL_CHITCHAT", "llama3.2"),
}

ACTIVE_MODEL = MODELS["router"]

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
4. NO INVENZIONE: Non inventare mai dati. Se usi un tool informativo, scrivi nella reply che stai controllando.
5. MEMORIA SEMANTICA: Riceverai blocchi di testo marcati come "CONTESTO PASSATO RILEVANTE". Questi sono ricordi recuperati dal database vettoriale. Usali per rispondere a domande su fatti passati o per coerenza a lungo termine.
6. ReAct LOOP: Puoi eseguire azioni multiple in sequenza. Se il risultato di un tool non è sufficiente, chiedi un altro tool nel prossimo step. Quando hai l'informazione finale, fornisci la "reply" senza "actions".
7. TOOL GENERATION: Puoi generare nuovi tool Python scrivendo codice nel tool 'code_generator'. Il codice deve essere salvato in 'plugins/'.

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
- code_generator: genera nuovi tool (filename, code)
- none: risposta solo testuale

REGOLE CRITICHE:
1. NON RIFIUTARE MAI: Hai accesso a internet tramite i tool. Se l'utente chiede prezzi, meteo o notizie, usa i tool dedicati.
2. FORMATO: Rispondi SOLO con il JSON, nessun altro testo.
3. Se l'utente chiede il valore di una moneta, usa sempre 'trading' con operation 'price'.
4. Se usi un tool informativo (trading, weather, search, news), nella tua "reply" NON inventare MAI dati o cifre. Dì solo che stai recuperando le informazioni (es: "Certamente, controllo subito..."). I dati reali verranno aggiunti automaticamente dopo.
"""

SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT_PERSONALITY", DEFAULT_PROMPT)

# ──────────────────────────────────────────────
# PROMPT SPECIALISTICI
# ──────────────────────────────────────────────

ROUTER_PROMPT = """Classifica l'intent dell'utente in UNA parola.
- DOMOTIC: se chiede PREZZI, BITCOIN, CRIPTO, S&P500, BORSA, AZIONI, METEO, NOTIZIE, WIKIPEDIA, LUCI, NOTE o CALENDARIO.
- REASONING: se chiede CODICE, spiegazioni lunghe, analisi o riassunti.
- CHITCHAT: se saluta, fa chiacchiere o domande personali.

Esempi:
"Quanto vale S&P500?" -> DOMOTIC
"Che tempo fa?" -> DOMOTIC
"Scrivi un loop" -> REASONING
"Ciao come stai" -> CHITCHAT

Rispondi SOLO con la categoria: DOMOTIC, REASONING o CHITCHAT."""

SPECIALIST_PROMPTS = {
    "DOMOTIC": DEFAULT_PROMPT + "\nFOCUS: Sii estremamente concisa e usa i tool appropriati. Rispondi SEMPRE in JSON.",
    "REASONING": DEFAULT_PROMPT + "\nFOCUS: Fornisci risposte approfondite e strutturate. Se l'utente chiede CODICE, scrivi codice pulito e commentato.",
    "CHITCHAT": DEFAULT_PROMPT + "\nFOCUS: Sii amichevole ma professionale (personalità 'tough'). Mantieni le risposte brevi.",
}

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

    async def _route_intent(self, user_input: str) -> str:
        """Determina l'intent dell'utente con logica ibrida: Hard Routing + LLM."""
        lower = user_input.lower()
        
        # 1. HARD ROUTING: Se ci sono parole chiave critiche, usa direttamente i tool
        tool_keywords = [
            "bitcoin", "btc", "eth", "cripto", "s&p", "sp500", "nasdaq", 
            "meteo", "news", "notizie", "borsa", "azioni", "prezzo", "valore",
            "luce", "chiudi", "apri", "wikipedia", "cerca", "search"
        ]
        if any(k in lower for k in tool_keywords):
            print(f"[ROUTER] Hard-routing rilevato: DOMOTIC")
            return "DOMOTIC"

        # 2. FAST PATH: se l'input è brevissimo e non è un tool, usa CHITCHAT
        if len(user_input.split()) <= 2:
            return "CHITCHAT"
            
        try:
            client = ollama.AsyncClient()
            response = await client.generate(
                model=MODELS["router"],
                system=ROUTER_PROMPT,
                prompt=user_input,
                stream=False,
                options={
                    "temperature": 0.0,
                    "num_predict": 10,  # Risposta brevissima
                },
                keep_alive="10m"  # Mantieni in VRAM per 10 minuti
            )
            intent = response.get("response", "CHITCHAT").strip().upper()
            # Pulizia output: cerca parole chiave nelle risposte discorsive
            for category in ["DOMOTIC", "REASONING", "CHITCHAT"]:
                if category in intent:
                    print(f"[ROUTER] Intent rilevato: {category}")
                    return category
            return "CHITCHAT"
        except Exception as e:
            print(f"[ROUTER] Errore routing: {e}")
            return "CHITCHAT"

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
        """Pipeline specialistica ottimizzata: Router e Retrieval in parallelo."""
        # 1. Avvia Routing e Retrieval semantico in parallelo per risparmiare tempo
        routing_task = asyncio.create_task(self._route_intent(user_input))
        context_task = asyncio.create_task(self.memory.get_context(query=user_input, top_k=5))
        
        # Aspetta il risultato del router
        intent = await routing_task
        
        # 2. Selezione Specialista
        model_key = intent.lower()
        model_name = MODELS.get(model_key, MODELS["chitchat"])
        system_prompt = SPECIALIST_PROMPTS.get(intent, DEFAULT_PROMPT)
        
        print(f"[PIPELINE] Specialist: {model_key.upper()} | Model: {model_name}")

        # Feedback all'utente se il modello è pesante
        if intent == "REASONING" and progress_cb:
            await progress_cb(random.choice(FILLER_MESSAGES))

        # 3. Chiamata allo Specialista
        try:
            # Aspetta che il contesto sia pronto (potrebbe essere già finito)
            context = await context_task
            prompt = f"{context}\nUtente: {user_input}"

            client = ollama.AsyncClient()
            response = await client.generate(
                model=model_name,
                system=system_prompt,
                prompt=prompt,
                format="json",
                stream=False,
                options={"temperature": 0.3 if intent == "CHITCHAT" else 0.1},
                keep_alive="10m"
            )

            text = response.get("response", "{}")
            result = self._clean_json(text)
            
            if "reply" not in result and "response" in result:
                result["reply"] = result["response"]
            
            return result

        except Exception as e:
            print(f"[LLM] Errore specialista {intent}: {e}")
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

    # ── PROCESSO PRINCIPALE (ReAct Loop) ──────────────────────────────
    async def process(self, user_input: str, progress_cb=None) -> str:
        """Pipeline completa ReAct: Ragiona → Agisci → Osserva."""

        # Salva input nella memoria
        await self.memory.add_turn("user", user_input)

        # 1. Controlla automazioni (fast path)
        auto_actions = self._check_automation(user_input)
        if auto_actions:
            await self._execute_actions(auto_actions)
            reply = f"Automazione '{user_input}' eseguita."
            await self.memory.add_turn("jarvis", reply)
            return reply

        # 2. ReAct Loop
        max_steps = 5
        current_step = 0
        context = await self.memory.get_context(query=user_input, top_k=5)
        
        # Inizializziamo la memoria di lavoro per il loop
        history = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"CONTESTO PASSATO RILEVANTE:\n{context}\n\nRichiesta utente: {user_input}"}
        ]

        final_reply = ""
        
        print(f"[ReAct] Avvio loop per: '{user_input}'")

        while current_step < max_steps:
            current_step += 1
            print(f"[ReAct] Step {current_step}...")

            # 2a. Chiedi all'LLM cosa fare
            try:
                client = ollama.AsyncClient()
                # Usiamo il modello reasoning o domotic per il loop ReAct
                intent = await self._route_intent(user_input)
                model_name = MODELS.get(intent.lower(), MODELS["domotic"])
                
                response = await client.chat(
                    model=model_name,
                    messages=history,
                    format="json",
                    options={"temperature": 0.1},
                    keep_alive="10m"
                )

                text = response["message"]["content"]
                plan = self._clean_json(text)
                
                actions = plan.get("actions", [])
                thought = plan.get("thought", "") # L'LLM può spiegare cosa sta facendo
                reply = plan.get("reply", "")

                if thought:
                    print(f"[ReAct] Pensiero: {thought}")

                # Se c'è una reply finale e nessuna azione, usciamo
                if not actions:
                    if reply:
                        final_reply = reply
                    else:
                        # LLM non ha fornito una reply valida → chiama lo specialista direttamente
                        print(f"[ReAct] Reply vuota — richiamo specialista per risposta finale.")
                        try:
                            fallback = await self._call_llm(user_input, progress_cb)
                            final_reply = fallback.get("reply") or "Come posso aiutarti?"
                        except Exception:
                            final_reply = "Come posso aiutarti?"
                    break

                # 2b. Eseguire azioni
                if actions:
                    if progress_cb and reply:
                        await progress_cb(reply)
                    
                    results = await self._execute_actions(actions)
                    
                    # 2c. Crea osservazione per il prossimo step
                    observation = ""
                    for res in results:
                        tool = res["tool"]
                        data = res["result"]
                        status = data.get("status", "error")
                        msg = data.get("message", "")
                        observation += f"Risultato tool '{tool}' ({status}): {msg}\n"

                    print(f"[ReAct] Osservazione: {observation.strip()}")
                    
                    # Aggiungi azione e osservazione alla storia
                    history.append({"role": "assistant", "content": text})
                    history.append({"role": "user", "content": f"OSSERVAZIONE: {observation}\nContinua se necessario o fornisci la risposta finale."})

            except Exception as e:
                print(f"[ReAct] Errore step {current_step}: {e}")
                final_reply = f"Errore durante l'elaborazione: {e}"
                break

        if not final_reply:
            final_reply = "Mi dispiace, il ragionamento ha richiesto troppi passaggi."

        # Salva risposta nella memoria
        await self.memory.add_turn("jarvis", final_reply)
        return final_reply
