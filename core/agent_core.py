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
import httpx
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
  "layout": "uno tra [orb, weather, map, browser, news, dashboard]",
  "layout_params": {"chiave": "valore"},
  "actions": [{"tool": "nome_tool", "parametro": "valore"}],
  "reply": "Tua risposta discorsiva e naturale in italiano"
}
REGOLE LAYOUT:
- weather: se l'utente chiede il meteo o previsioni (params: location).
- map: se l'utente chiede una posizione geografica o indicazioni (params: query, zoom).
- browser: se devi mostrare un sito web specifico o ricerca (params: url).
- news: se l'utente chiede ultime notizie (params: category).
- dashboard: per riepiloghi generali o stato casa.
- orb: default per chitchat o quando non serve un pannello specifico.

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
- mqtt: controllo multi-room (room, device, state)
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
        self._last_layout = {"type": "orb", "params": {}}

    async def initialize(self):
        """Inizializza tutti i componenti."""
        self.tool_manager.initialize()
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
        words = lower.split()
        word_count = len(words)
        
        # --- 0. ECCEZIONI (MAI HARD-ROUTE) ---
        # Se contiene citazioni, domande di spiegazione o è troppo lunga
        never_hard_route = [
            "parla di", "spiegami", "cosa pensi", "perché", "come mai", "cosa significa"
        ]
        if (any(x in lower for x in never_hard_route) or 
            '"' in user_input or 
            "'" in user_input or
            word_count > 12):
            return await self._llm_routing(user_input)

        # --- 1. HARD ROUTING: DOMOTIC ---
        # Azione hardware esplicita: VERBO + OGGETTO
        domotic_verbs = ["accendi", "spegni", "apri", "chiudi"]
        domotic_objects = ["luce", "led", "relè", "servo", "tapparella"]
        if any(v in lower for v in domotic_verbs) and any(o in lower for o in domotic_objects):
            print(f"[ROUTER] Hard-routing rilevato: DOMOTIC (Hardware)")
            return "DOMOTIC"

        # Finanza: PREZZO/QUANTO VALE + ASSET
        crypto_verbs = ["prezzo", "quanto vale", "quotazione"]
        crypto_assets = ["bitcoin", "btc", "eth", "ethereum", "crypto", "azioni", "sp500", "nasdaq"]
        if any(v in lower for v in crypto_verbs) and any(a in lower for a in crypto_assets):
            print(f"[ROUTER] Hard-routing rilevato: DOMOTIC (Finance)")
            return "DOMOTIC"

        # Meteo e News (già filtrati per lunghezza > 12 sopra)
        if any(x in lower for x in ["meteo", "che tempo fa", "temperatura"]):
            print(f"[ROUTER] Hard-routing rilevato: DOMOTIC (Meteo)")
            return "DOMOTIC"
        
        if any(x in lower for x in ["ultime notizie", "che news", "cosa è successo oggi"]):
            print(f"[ROUTER] Hard-routing rilevato: DOMOTIC (News)")
            return "DOMOTIC"

        # Spotify: VERBO + OGGETTO
        spotify_verbs = ["metti", "riproduci", "play", "pausa", "prossimo brano", "volume"]
        spotify_objects = ["musica", "spotify", "canzone", "brano"]
        if any(v in lower for v in spotify_verbs) and any(o in lower for o in spotify_objects):
            print(f"[ROUTER] Hard-routing rilevato: DOMOTIC (Spotify)")
            return "DOMOTIC"

        # --- 2. HARD ROUTING: CHITCHAT ---
        # Saluto puro o messaggio brevissimo senza keyword tool
        greetings = ["ciao", "hey", "salve", "buon"]
        is_greeting = any(lower.startswith(g) for g in greetings)
        
        # Se è un saluto e non ci sono altre keyword (finanza/meteo/ecc già controllate sopra)
        if is_greeting and word_count <= 4:
            print(f"[ROUTER] Hard-routing rilevato: CHITCHAT (Saluto)")
            return "CHITCHAT"
        
        if word_count <= 2:
            print(f"[ROUTER] Hard-routing rilevato: CHITCHAT (Short)")
            return "CHITCHAT"

        # --- 3. FALLBACK LLM ---
        return await self._llm_routing(user_input)

    async def _llm_routing(self, user_input: str) -> str:
        """Routing tramite LLM (Groq -> Ollama)."""
        try:
            # PRIORITÀ GROQ PER ROUTING
            if os.getenv("GROQ_API_KEY"):
                messages = [
                    {"role": "system", "content": ROUTER_PROMPT},
                    {"role": "user", "content": user_input}
                ]
                response_text = await self._call_groq(messages, json_mode=False)
                if response_text:
                    intent = response_text.strip().upper()
                    for category in ["DOMOTIC", "REASONING", "CHITCHAT"]:
                        if category in intent:
                            print(f"[ROUTER] Intent rilevato (Groq): {category}")
                            return category

            # FALLBACK OLLAMA
            client = ollama.AsyncClient()
            response = await client.generate(
                model=MODELS["router"],
                system=ROUTER_PROMPT,
                prompt=user_input,
                stream=False,
                options={
                    "temperature": 0.0,
                    "num_predict": 10,
                },
                keep_alive="10m"
            )
            intent = response.get("response", "CHITCHAT").strip().upper()
            for category in ["DOMOTIC", "REASONING", "CHITCHAT"]:
                if category in intent:
                    print(f"[ROUTER] Intent rilevato: {category}")
                    return category
            return "CHITCHAT"
        except Exception as e:
            print(f"[ROUTER] Errore routing LLM: {e}")
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
            result = json.loads(text)
            # Salvataggio layout per propagazione
            self._last_layout = {
                "type": result.get("layout", "orb"),
                "params": result.get("layout_params", {})
            }
            return result
        except json.JSONDecodeError:
            result = self._fallback_parse(text)
            self._last_layout = {"type": "orb", "params": {}}
            return result

    async def _call_groq(self, messages, json_mode=True):
        """Chiamata primaria a Groq."""
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return None

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        
        # Scegli il modello in base al contenuto dei messaggi (se router o meno)
        # Se json_mode è False, probabilmente siamo nel routing
        model_env = "GROQ_ROUTER_MODEL" if not json_mode else "GROQ_MODEL"
        default_model = "llama-3.1-8b-instant" if not json_mode else "llama-3.3-70b-versatile"
        model = os.getenv(model_env, default_model)

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[GROQ] Errore: {e}")
            return None

    async def _call_groq_fallback(self, messages: list) -> dict:
        """Chiamata di fallback a Groq se Ollama non è disponibile."""
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            print("[LLM] Groq fallback saltato: GROQ_API_KEY non trovata.")
            return {}

        print("[LLM] Utilizzo fallback Groq (Llama 3.3 70B)...")
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 1000
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                text = data["choices"][0]["message"]["content"]
                return self._clean_json(text)
        except Exception as e:
            print(f"[LLM] Errore critico Groq fallback: {e}")
            return {}

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
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]

            # PRIORITÀ GROQ
            if os.getenv("GROQ_API_KEY"):
                response_text = await self._call_groq(messages, json_mode=True)
                if response_text:
                    return self._clean_json(response_text)

            # FALLBACK OLLAMA
            try:
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

            except (ollama.ResponseError, httpx.ConnectError, ConnectionError) as e:
                print(f"[LLM] Ollama non raggiungibile ({e}). Provo fallback Groq...")
                groq_res = await self._call_groq_fallback(messages)
                if groq_res:
                    return groq_res
                raise # Rilancia per il fallback parse se anche Groq fallisce
        
        except Exception as e:
            print(f"[LLM] Errore pipeline {intent}: {e}")
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
            from datetime import datetime
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
            actions.append(
                {
                    "tool": "calendar",
                    "action": "add",
                    "title": user_input,
                    "time": now_str,
                }
            )
            reply = f"Evento aggiunto al calendario ({now_str})."
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

            # --- BROADCAST AUTOMATICO PER DASHBOARD ---
            if self.socket_manager:
                # Mappa i tool ai messaggi websocket
                ws_map = {
                    "weather": "weather",
                    "spotify": "spotify",
                    "calendar": "calendar",
                    "trading": "trading",
                    "sys_monitor": "stats"
                }
                
                if tool_name in ws_map and result.get("status") == "ok":
                    msg_type = ws_map[tool_name]
                    # Alcuni tool mettono i dati in 'data', altri no
                    payload = {"type": msg_type}
                    
                    if "data" in result:
                        if isinstance(result["data"], dict):
                            payload.update(result["data"])
                        else:
                            payload["data"] = result["data"]
                    else:
                        # Fallback: metti tutto il risultato nel payload
                        payload.update(result)
                    
                    # Rimuovi campi ridondanti
                    payload.pop("status", None)
                    payload.pop("message", None)
                    
                    print(f"[EXECUTOR] Broadcasting {msg_type} for dashboard")
                    await self.socket_manager.broadcast(payload)

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
    async def process(self, user_input: str, progress_cb=None):
        """Pipeline completa ReAct: Ragiona → Agisci → Osserva."""
        # Salva input nella memoria
        await self.memory.add_turn("user", user_input)

        # 1. Controlla automazioni (fast path)
        auto_actions = self._check_automation(user_input)
        if auto_actions:
            await self._execute_actions(auto_actions)
            reply = f"Automazione '{user_input}' eseguita."
            await self.memory.add_turn("jarvis", reply)
            yield reply
            return

        # 2. ReAct Loop
        max_steps = 5
        current_step = 0
        
        # 2a. Determina l'intent UNA VOLTA sola fuori dal loop (Pipeline specialistica)
        intent = await self._route_intent(user_input)

        # --- FAST PATH: CHITCHAT SINGLE-SHOT ---
        if intent == "CHITCHAT":
            print(f"[PIPELINE] Single-shot CHITCHAT per: '{user_input}'")
            messages = [
                {"role": "system", "content": SPECIALIST_PROMPTS["CHITCHAT"]},
                {"role": "user", "content": user_input}
            ]
            
            res_text = None
            if os.getenv("GROQ_API_KEY"):
                res_text = await self._call_groq(messages, json_mode=True)
            
            if not res_text:
                client = ollama.AsyncClient()
                response = await client.chat(
                    model=MODELS["chitchat"],
                    messages=messages,
                    format="json",
                    options={"temperature": 0.7},
                    keep_alive="10m"
                )
                res_text = response["message"]["content"]
            
            result = self._clean_json(res_text)
            final_reply = result.get("reply", "")
            if final_reply:
                for token in re.findall(r'.*?\s|.*$', final_reply):
                    yield token
                await self.memory.add_turn("jarvis", final_reply)
                return

        context = await self.memory.get_context(query=user_input, top_k=5)
        
        # Inizializziamo la memoria di lavoro per il loop
        history = [
            {"role": "system", "content": SPECIALIST_PROMPTS.get(intent, DEFAULT_PROMPT)},
            {"role": "user", "content": f"CONTESTO PASSATO RILEVANTE:\n{context}\n\nRichiesta utente: {user_input}"}
        ]

        final_reply = ""
        model_name = MODELS.get(intent.lower(), MODELS["domotic"])
        
        print(f"[ReAct] Avvio loop ({intent}) per: '{user_input}'")

        while current_step < max_steps:
            current_step += 1
            print(f"[ReAct] Step {current_step}...")

            # 2b. Chiedi all'LLM cosa fare
            try:
                full_response_text = ""
                
                # PRIORITÀ GROQ
                if os.getenv("GROQ_API_KEY"):
                    full_response_text = await self._call_groq(history, json_mode=True)
                
                # FALLBACK OLLAMA
                if not full_response_text:
                    client = ollama.AsyncClient()
                    
                    # Streaming della risposta dell'LLM
                    # Se è l'ultimo step o un'intent semplice, possiamo fare streaming della reply.
                    # Ma qui riceviamo un JSON, quindi non possiamo streammare il JSON grezzo all'utente.
                    # Lo streaming dei token ha senso solo se sappiamo che è la risposta finale.
                    
                    response = await client.chat(
                        model=model_name,
                        messages=history,
                        format="json",
                        options={"temperature": 0.1},
                        keep_alive="10m",
                        stream=False
                    )
                    full_response_text = response["message"]["content"]
                
                plan = self._clean_json(full_response_text)
                
                actions = plan.get("actions", [])
                thought = plan.get("thought", "")
                reply = plan.get("reply", "")

                if thought:
                    print(f"[ReAct] Pensiero: {thought}")

                # Se non ci sono azioni, abbiamo finito: streammiano la reply finale
                if not actions:
                    if reply:
                        final_reply = reply
                        # Stream the final reply token by token
                        for token in re.findall(r'.*?\s|.*$', final_reply):
                            yield token
                            await asyncio.sleep(0.02) # Piccola pausa per effetto streaming
                    else:
                        print(f"[ReAct] Reply vuota — richiamo pipeline specialistica.")
                        fallback = await self._call_llm(user_input, progress_cb)
                        final_reply = fallback.get("reply") or "Come posso aiutarti?"
                        for token in re.findall(r'.*?\s|.*$', final_reply):
                            yield token
                            await asyncio.sleep(0.01)
                    break

                # 2c. Eseguire azioni
                if actions:
                    if progress_cb and reply:
                        await progress_cb(reply)
                    
                    results = await self._execute_actions(actions)
                    
                    # 2d. Crea osservazione per il prossimo step
                    observation = ""
                    for res in results:
                        tool = res["tool"]
                        data = res["result"]
                        status = data.get("status", "error")
                        msg = data.get("message", "")
                        observation += f"Risultato tool '{tool}' ({status}): {msg}\n"

                    print(f"[ReAct] Osservazione: {observation.strip()}")
                    
                    # --- EARLY EXIT CHECK ---
                    # Se abbiamo usato un solo tool (non critico), il risultato è OK e abbiamo già una reply
                    # consistente, usciamo senza fare lo Step 2 (riformulazione).
                    is_error = any(res.get("result", {}).get("status") == "error" for res in results)
                    is_short_q_reply = "?" in user_input and len(reply) < 30
                    
                    critical_tools = ["none", "code_generator"]
                    has_critical_tool = any(res["tool"] in critical_tools for res in results)
                    
                    if (not is_error and 
                        len(actions) == 1 and 
                        not has_critical_tool and 
                        len(reply) > 15 and 
                        not is_short_q_reply):
                        print(f"[ReAct] Early Exit: risposta soddisfacente dopo Step 1.")
                        final_reply = reply
                        for token in re.findall(r'.*?\s|.*$', final_reply):
                            yield token
                        break

                    # Aggiungi azione e osservazione alla storia
                    history.append({"role": "assistant", "content": full_response_text})
                    history.append({"role": "user", "content": f"OSSERVAZIONE: {observation}\nContinua se necessario o fornisci la risposta finale."})

            except Exception as e:
                print(f"[ReAct] Errore step {current_step}: {e}")
                final_reply = f"Errore durante l'elaborazione: {e}"
                yield final_reply
                break

        if not final_reply and current_step >= max_steps:
            final_reply = "Mi dispiace, il ragionamento ha richiesto troppi passaggi."
            yield final_reply

        # Salva risposta nella memoria
        await self.memory.add_turn("jarvis", final_reply)
        
        # In un async generator non si può usare 'return value' prima di Python 3.10 
        # o in contesti specifici. Usiamo un attributo per passare il layout finale.
        self._last_final_data = (final_reply, getattr(self, '_last_layout', {"type": "orb", "params": {}}))
