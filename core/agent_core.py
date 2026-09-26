"""Core orchestration for M.A.Y.A., without hardware-specific integrations."""

from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata
from collections import OrderedDict
from datetime import datetime, timedelta

import httpx
import ollama
from dotenv import load_dotenv

from .audit.logger import AuditLogger
from .automation_engine import Automation, AutomationEngine, build_default_automations
from .automation_engine import engine as automation_engine
from .fast_path import FastPathRouter
from .memory.structured import StructuredMemory
from .memory_manager import MemoryManager
from .permissions.engine import PermissionEngine
from .preference_learner import PreferenceLearner
from .token_juice import compress_tool_output
from .tool_manager import ToolManager
from .yaml_automations import load_yaml_automations

load_dotenv()
os.environ["OLLAMA_HOST"] = os.getenv("OLLAMA_HOST", "127.0.0.1")


def is_ollama_enabled() -> bool:
    return os.getenv("OLLAMA_ENABLED", "true").strip().lower() in {"1", "true", "yes"}


MODELS = {
    "router": os.getenv("MODEL_ROUTER", "llama3.2:1b"),
    "domotic": os.getenv("MODEL_DOMOTIC", "phi4"),
    "reasoning": os.getenv("MODEL_REASONING", "mistral-small"),
    "chitchat": os.getenv("MODEL_CHITCHAT", "llama3.2"),
}
ACTIVE_MODEL = MODELS["router"]

DEFAULT_PROMPT = """Sei MAYA, un assistente personale locale e operativo.
Rispondi esclusivamente con JSON valido contenente intent, layout, layout_params, actions e reply.
Usa i tool solo quando servono. Non inventare dati restituiti dai tool.
Tool disponibili: calendar, weather, news, notes, timer, search, spotify, system, mqtt,
display, sys_monitor, browser, home_assistant e none. MQTT e Home Assistant sono canali domotici.
Le azioni devono avere il nome tool e i parametri canonici al primo livello.
Quando non serve un tool usa actions=[] e una reply completa in italiano."""
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT_PERSONALITY", DEFAULT_PROMPT)

ROUTER_PROMPT = """Classifica in una parola: DOMOTIC per tool, servizi, MQTT, meteo,
notizie, calendario e note; CODING per richieste di codice; REASONING per conoscenza e
analisi; CHITCHAT solo per conversazione sociale breve."""

SPECIALIST_PROMPTS = {
    "DOMOTIC": DEFAULT_PROMPT,
    "CODING": DEFAULT_PROMPT + "\nPer il codice sii preciso e conciso.",
    "REASONING": DEFAULT_PROMPT + "\nFornisci una risposta ragionata.",
    "CHITCHAT": DEFAULT_PROMPT + "\nMantieni la risposta breve.",
}


class AgentCore:
    """Planner/executor with deterministic fast paths and a bounded ReAct loop."""

    def __init__(self):
        self.tool_manager = ToolManager()
        self.memory = MemoryManager()
        self.structured_memory = StructuredMemory()
        self.audit = AuditLogger(self.structured_memory.database_path)
        self.permissions = PermissionEngine()
        self.telegram_confirmation = None
        self.learner = PreferenceLearner()
        self.automation_engine: AutomationEngine = automation_engine
        self.socket_manager = None
        self.voice_manager = None
        self.loop = None
        self._intent_cache: OrderedDict[str, str] = OrderedDict()
        self._last_layout = {"type": "orb", "params": {}}
        self._last_final_data = ("", self._last_layout)
        self._current_task_layout: dict = {}
        self._current_task_final_data: dict = {}
        self._last_groq_error_status: int | None = None

    async def initialize(self):
        self.tool_manager.initialize()
        self.structured_memory.initialize()
        self.structured_memory.migrate_legacy_notes()
        self.audit.initialize()
        self.memory.load()
        await self.memory.migrate_json_to_chroma()
        self.automation_engine._tool_manager = self.tool_manager
        self.automation_engine.memory = self.memory
        self.automation_engine.socket_manager = self.socket_manager
        self.automation_engine.voice_manager = self.voice_manager
        self.automation_engine.register_all(build_default_automations())
        self.automation_engine.register_all(
            load_yaml_automations(os.getenv("MAYA_AUTOMATIONS_FILE", "data/automations.yaml"))
        )
        asyncio.create_task(self.automation_engine.start_scheduler())
        for text in ("che tempo fa", "meteo", "ultime notizie", "spotify next"):
            self._intent_cache[text] = "DOMOTIC"
        for text in ("ciao", "ciao maya", "grazie"):
            self._intent_cache[text] = "CHITCHAT"

    def _check_automation(self, user_input: str) -> Automation | None:
        return self.automation_engine.resolve(user_input)

    def _normalize_router_text(self, text: str) -> str:
        text = unicodedata.normalize("NFKD", text.lower())
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", text)).strip()

    def _strip_wake_prefix(self, text: str) -> str:
        return re.sub(r"^(?:hey\s+|ehi\s+)?maya[,:]?\s*", "", text, flags=re.IGNORECASE).strip()

    def _is_chitchat_input(self, text: str) -> bool:
        normalized = self._normalize_router_text(text)
        return bool(
            re.fullmatch(
                r"(?:ciao|hey|ehi|salve|buongiorno|buonasera|grazie)(?: maya)?(?: come stai| come va)?", normalized
            )
        )

    def _is_knowledge_question(self, text: str) -> bool:
        normalized = self._normalize_router_text(text)
        patterns = (
            r"\b(?:chi|che|cosa|cos) e\b",
            r"\b(?:parlami|raccontami) di\b",
            r"\b(?:spiegami|spiega|definisci)\b",
            r"\b(?:perche|come mai|cosa significa)\b",
        )
        return any(re.search(pattern, normalized) for pattern in patterns)

    async def _route_intent(self, user_input: str) -> str:
        key = user_input.lower().strip()[:80]
        if key in self._intent_cache:
            self._intent_cache.move_to_end(key)
            return self._intent_cache[key]
        intent = await self._route_intent_uncached(user_input)
        self._intent_cache[key] = intent
        if len(self._intent_cache) > 500:
            self._intent_cache.popitem(last=False)
        return intent

    async def _route_intent_uncached(self, user_input: str) -> str:
        text = self._normalize_router_text(self._strip_wake_prefix(user_input))
        if self._is_knowledge_question(text):
            return "REASONING"
        if self._is_chitchat_input(text):
            return "CHITCHAT"
        if re.search(r"\b(?:scrivi|programma|codice|funzione|python|javascript|bug)\b", text):
            return "CODING"
        if re.search(r"\b(?:meteo|tempo fa|notizie|news|calendario|agenda|nota|spotify|mqtt|luce|luci|casa)\b", text):
            return "DOMOTIC"
        return await self._llm_routing(user_input)

    async def _llm_routing(self, user_input: str) -> str:
        result = await self._call_groq(
            [{"role": "system", "content": ROUTER_PROMPT}, {"role": "user", "content": user_input}],
            json_mode=False,
        )
        intent = str(result or "").strip().upper()
        if intent == "CHITCHAT" and not self._is_chitchat_input(user_input):
            return "REASONING"
        return intent if intent in SPECIALIST_PROMPTS else "REASONING"

    @staticmethod
    def _clean_json(text: str) -> dict:
        if not isinstance(text, str):
            return {}
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        return {}

    async def _call_groq(self, messages, json_mode=True):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return None
        payload = {
            "model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
            "messages": messages,
            "temperature": 0.1,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
            self._last_groq_error_status = response.status_code if response.status_code >= 400 else None
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return self._clean_json(content) if json_mode else content
        except httpx.HTTPStatusError as exc:
            self._last_groq_error_status = exc.response.status_code
            return None
        except Exception:
            return None

    async def _call_groq_fallback(self, messages: list) -> dict | None:
        result = await self._call_groq(messages, json_mode=True)
        return result if isinstance(result, dict) else None

    async def _call_llm(self, user_input: str, progress_cb=None) -> dict:
        intent = await self._route_intent(user_input)
        context = await self.memory.get_context(user_input)
        messages = [
            {"role": "system", "content": SPECIALIST_PROMPTS[intent]},
            {"role": "user", "content": f"{context}\n\nRICHIESTA: {user_input}"},
        ]
        if is_ollama_enabled():
            try:
                response = await ollama.AsyncClient().chat(
                    model=MODELS.get(intent.lower(), MODELS["reasoning"]), messages=messages, format="json"
                )
                return self._clean_json(response.get("message", {}).get("content", "{}"))
            except Exception:
                pass
        fallback = await self._call_groq_fallback(messages)
        if fallback:
            return fallback
        if self._last_groq_error_status == 429:
            return {"actions": [], "reply": "Ho raggiunto il limite di richieste del servizio cloud. Riprova tra poco."}
        return {"actions": [], "reply": "Il modello locale non e disponibile e il fallback cloud non ha risposto."}

    def _fallback_parse(self, user_input: str) -> dict:
        return {"intent": "fallback", "actions": [], "reply": "Il modello non e disponibile per questa richiesta."}

    async def _execute_actions(self, actions: list, source_text: str = "") -> list:
        results = []
        for action in actions:
            tool_name = action.get("tool", "none")
            decision = self.permissions.decide(action)
            if not decision.allowed and source_text.startswith("telegram:"):
                _, chat_id, user_id = source_text.split(":", 2)
                if self.telegram_confirmation and chat_id:
                    await self.telegram_confirmation(chat_id, user_id, action)
                self.audit.record(
                    "action_confirmation_required", details={"tool": tool_name, "reason": decision.reason}
                )
                results.append(
                    {
                        "tool": tool_name,
                        "result": {"status": "error", "message": "Azione sensibile: conferma richiesta."},
                    }
                )
                continue
            result = await self.tool_manager.execute(action)
            if tool_name in self.permissions.SENSITIVE_TOOLS:
                self.audit.record(
                    "sensitive_action_executed", details={"tool": tool_name, "status": result.get("status")}
                )
            results.append({"tool": tool_name, "result": result})
        return results

    def _validate_results(self, results: list) -> bool:
        return all(item.get("result", {}).get("status") != "error" for item in results)

    def _set_final_layout(self, reply: str, layout: dict):
        task = asyncio.current_task()
        final_data = (reply, layout)
        if task:
            self._current_task_final_data[task] = final_data
        else:
            self._last_final_data = final_data

    async def _reply_fast(self, reply: str, layout: dict | None = None):
        await self.memory.add_turn("jarvis", reply, persist_db=False)
        asyncio.create_task(self.memory.add_turn("jarvis", reply, persist_db=True))
        self._set_final_layout(reply, layout or {"type": "current", "params": {}})
        return reply

    def _parse_direct_calendar_command(self, text: str) -> tuple[dict | None, str] | None:
        return FastPathRouter.calendar(text)

    def _parse_direct_calendar_command_legacy(self, text: str) -> tuple[dict | None, str] | None:
        if re.search(r"\b(?:prossim[oi]|mostra|lista|elenca|cos[' ]?ho|cosa ho|ho)\b", text) and re.search(
            r"\b(?:calendario|eventi|agenda)\b", text
        ):
            return ({"tool": "calendar", "action": "list"}, "Ecco i prossimi eventi.")
        if re.search(r"\b(?:cancella|elimina|rimuovi)\b", text) and re.search(r"\b(?:evento|appuntamento)\b", text):
            title = re.sub(r"\b(?:cancella|elimina|rimuovi|evento|appuntamento|il|la)\b", " ", text)
            title = re.sub(r"\s+", " ", title).strip(" .,;:-")
            return (
                ({"tool": "calendar", "action": "delete", "title": title}, f"Cancello l'evento '{title}'.")
                if title
                else (None, "Dimmi il titolo dell'evento da cancellare.")
            )
        return None

    async def _run_direct_calendar_command(self, parsed: tuple[dict | None, str], source: str = "local") -> str:
        action, fallback = parsed
        if action is None:
            return fallback
        result = (await self._execute_actions([action], source))[0]["result"]
        return result.get("message", fallback)

    def _parse_direct_structured_memory_command(self, text: str) -> tuple[str, dict] | None:
        return FastPathRouter.structured_memory(text)

    def _parse_direct_structured_memory_command_legacy(self, text: str) -> tuple[str, dict] | None:
        reminder = re.fullmatch(
            r"ricordami\s+(oggi|domani)(?:\s+alle\s+(\d{1,2})(?::(\d{2}))?)?\s+(?:che\s+)?(.+)", text
        )
        if reminder:
            day, hour, minute, content = reminder.groups()
            due_at = datetime.now().astimezone().replace(second=0, microsecond=0)
            if day == "domani":
                due_at += timedelta(days=1)
            due_at = due_at.replace(hour=int(hour or 9), minute=int(minute or 0))
            return "reminder", {"content": content.strip(), "due_at": due_at}
        note = re.fullmatch(r"(?:segnati|annota|prendi nota)(?:\s+che)?\s+(.+)", text)
        if note:
            content = note.group(1).strip()
            lent = re.fullmatch(r"ho prestato (?:il|lo|la|i|gli|le)\s+(.+?)\s+a\s+(.+)", content)
            if lent:
                return "fact", {"subject": lent.group(1), "value": f"Prestato a {lent.group(2)}"}
            return "note", {"content": content}
        lookup = re.fullmatch(r"(?:dove|dov['’][eè])\s+(?:il|lo|la|i|gli|le)?\s*(.+?)[?!.]*", text)
        return ("fact_lookup", {"query": lookup.group(1).strip()}) if lookup else None

    async def _run_direct_structured_memory_command(self, parsed: tuple[str, dict]) -> str:
        operation, data = parsed
        self.structured_memory.initialize()
        if operation == "invalid":
            return data["message"]
        if operation == "note":
            self.structured_memory.add_note(data["content"])
            return "Nota salvata."
        if operation == "fact":
            fact = self.structured_memory.remember_fact(data["subject"], data["value"])
            return f"Segnato: {fact['subject']} — {fact['value']}."
        if operation == "reminder":
            reminder = self.structured_memory.add_reminder(data["content"], data["due_at"])
            due_at = datetime.fromisoformat(reminder["due_at"]).astimezone()
            return f"Promemoria impostato per il {due_at:%d/%m alle %H:%M}: {reminder['content']}."
        facts = self.structured_memory.find_facts(data["query"])
        return (
            "\n".join(f"{fact['subject']}: {fact['value']}" for fact in facts)
            if facts
            else "Non ho trovato nulla nella memoria personale."
        )

    def _parse_direct_weather_command(self, text: str) -> dict | None:
        if text in {"temperatura casa", "temperatura in casa"}:
            return None
        match = re.fullmatch(r"(?:che tempo fa|meteo|previsioni)(?:\s+(?:a|per)\s+(.+?))?[?!.]*", text)
        return (
            {"tool": "weather", "location": match.group(1).strip().title() if match and match.group(1) else None}
            if match
            else None
        )

    async def _run_direct_weather_command(self, action: dict) -> str:
        result = await self.tool_manager.execute(action)
        data = result.get("data", {})
        if result.get("status") != "ok" or not data:
            return result.get("message", "Meteo non disponibile.")
        location = data.get("location", action.get("location") or "la localita richiesta")
        temp = data.get("temp")
        condition = data.get("condition")
        parts = [f"A {location}"]
        if condition:
            parts.append(str(condition).lower())
        if temp is not None:
            parts.append(f"{round(float(temp))} gradi")
        return ", ".join(parts) + "."

    def _parse_direct_news_command(self, text: str) -> dict | None:
        return (
            {"tool": "news", "limit": 5}
            if re.fullmatch(r"(?:dimmi\s+)?(?:le\s+)?(?:ultime\s+)?(?:news|notizie)[?!.]*", text)
            else None
        )

    async def _run_direct_news_command(self, action: dict) -> str:
        result = await self.tool_manager.execute(action)
        return result.get("message", "Notizie non disponibili.")

    def _parse_direct_knowledge_command(self, text: str) -> dict | None:
        match = re.fullmatch(r"(?:parlami|raccontami)\s+di\s+(.+?)[?!.]*", text, flags=re.IGNORECASE)
        if not match:
            return None
        return {"tool": "search", "query": self._normalize_knowledge_query(match.group(1).strip())}

    @staticmethod
    def _normalize_knowledge_query(query: str) -> str:
        aliases = {"napoleone": "Napoleone Bonaparte", "manzoni": "Alessandro Manzoni"}
        return aliases.get(query.casefold(), query)

    async def _run_direct_knowledge_command(self, action: dict) -> str:
        result = await self.tool_manager.execute(action)
        return result.get("message", "Ricerca non disponibile.")

    def _capabilities_reply(self, text: str) -> str | None:
        if not re.search(r"\b(?:cosa sai fare|funzioni|capacita|capabilities)\b", self._normalize_router_text(text)):
            return None
        return "Posso gestire calendario, memoria, meteo, notizie, timer, ricerca, Spotify, MQTT e funzioni di sistema."

    async def _stop_alarm_direct(self) -> str:
        self.automation_engine._cancel_background_tasks("allarme")
        return "Allarme fermato."

    async def _open_dashboard_panel(self, layout: str) -> str:
        if self.socket_manager:
            await self.socket_manager.broadcast({"type": "layout", "layout": layout})
        return f"Pannello {layout} aperto."

    async def process(self, user_input: str, progress_cb=None, source: str = "local"):
        for cache in (self._current_task_layout, self._current_task_final_data):
            for task in list(cache):
                if task.done():
                    cache.pop(task, None)
        await self.memory.add_turn("user", user_input, persist_db=False)
        clean = self._strip_wake_prefix(user_input.strip()).lower()
        original = self._strip_wake_prefix(user_input.strip())

        fast_paths = [
            (self._parse_direct_weather_command(clean), self._run_direct_weather_command, "weather"),
            (self._parse_direct_news_command(clean), self._run_direct_news_command, "news"),
            (self._parse_direct_knowledge_command(original), self._run_direct_knowledge_command, "chat"),
        ]
        for parsed, runner, layout in fast_paths:
            if parsed:
                yield await self._reply_fast(await runner(parsed), {"type": layout, "params": {}})
                return

        direct_memory = self._parse_direct_structured_memory_command(clean)
        if direct_memory:
            yield await self._reply_fast(
                await self._run_direct_structured_memory_command(direct_memory), {"type": "chat", "params": {}}
            )
            return
        direct_calendar = self._parse_direct_calendar_command(clean)
        if direct_calendar:
            yield await self._reply_fast(
                await self._run_direct_calendar_command(direct_calendar, source), {"type": "calendar", "params": {}}
            )
            return
        capabilities = self._capabilities_reply(clean)
        if capabilities:
            yield await self._reply_fast(capabilities, {"type": "dashboard", "params": {}})
            return
        if re.search(r"\b(?:ferma|stop|spegni|disattiva)\b", clean) and re.search(
            r"\b(?:allarme|alarme|all['’]?armi)\b", clean
        ):
            yield await self._reply_fast(await self._stop_alarm_direct())
            return

        automation = self._check_automation(clean)
        if automation:
            if source.startswith("telegram:"):
                sensitive = next(
                    (
                        item.to_tool_action()
                        for item in automation.scene.actions
                        if not self.permissions.decide(item.to_tool_action()).allowed
                    ),
                    None,
                )
                if sensitive:
                    _, chat_id, user_id = source.split(":", 2)
                    if self.telegram_confirmation:
                        await self.telegram_confirmation(chat_id, user_id, sensitive)
                    yield await self._reply_fast("Azione sensibile: conferma richiesta.")
                    return
            outcome = await self.automation_engine.execute(automation, source="manual")
            yield await self._reply_fast(outcome.get("message", f"Automazione {automation.name} eseguita."))
            return

        intent = await self._route_intent(user_input)
        context = await self.memory.get_context(user_input)
        history = [
            {"role": "system", "content": SPECIALIST_PROMPTS[intent]},
            {"role": "user", "content": f"{context}\n\nRICHIESTA: {user_input}"},
        ]
        max_steps = int(os.getenv("REACT_MAX_STEPS", "2"))
        final_reply = ""
        current_step = 0
        while current_step < max_steps:
            current_step += 1
            try:
                plan = None
                full_response_text = ""
                if is_ollama_enabled():
                    try:
                        response = await ollama.AsyncClient().chat(
                            model=MODELS.get(intent.lower(), MODELS["reasoning"]), messages=history, format="json"
                        )
                        full_response_text = response.get("message", {}).get("content", "{}")
                        plan = self._clean_json(full_response_text)
                    except Exception:
                        plan = None
                if not plan:
                    plan = await self._call_groq(history, json_mode=True)
                    full_response_text = json.dumps(plan or {}, ensure_ascii=False)
                if not plan:
                    final_reply = (
                        "Ho raggiunto il limite di richieste del servizio cloud. Riprova tra poco."
                        if self._last_groq_error_status == 429
                        else "Il modello non e disponibile."
                    )
                    yield final_reply
                    break
                actions = plan.get("actions") or []
                reply = plan.get("reply", "")
                if not actions:
                    final_reply = reply or "Come posso aiutarti?"
                    for token in (word + " " for word in final_reply.split()):
                        yield token
                    break
                if reply:
                    yield reply + " "
                    if progress_cb:
                        await progress_cb(reply)
                results = await self._execute_actions(actions, source)
                self.learner.observe_command(user_input, actions)
                is_error = any(item["result"].get("status") == "error" for item in results)
                needs_rephrase = any(
                    item["tool"] in {"none", "weather", "news", "search", "calendar"} for item in results
                )
                if not is_error and not needs_rephrase and len(reply) > 15:
                    final_reply = reply
                    break
                observation = "\n".join(
                    f"Risultato tool '{item['tool']}' ({item['result'].get('status', 'error')}): {compress_tool_output(item['tool'], str(item['result'].get('message', '')))}"
                    for item in results
                )
                history.append({"role": "assistant", "content": full_response_text})
                history.append(
                    {"role": "user", "content": f"OSSERVAZIONE: {observation}\nContinua o fornisci la risposta finale."}
                )
            except Exception as exc:
                final_reply = f"Errore durante l'elaborazione: {exc}"
                yield final_reply
                break
        if not final_reply and current_step >= max_steps:
            final_reply = "Mi dispiace, il ragionamento ha richiesto troppi passaggi."
            yield final_reply
        await self.memory.add_turn("jarvis", final_reply, persist_db=False)
        asyncio.create_task(self.memory.add_turn("jarvis", final_reply, persist_db=True))
        task = asyncio.current_task()
        layout = self._current_task_layout.pop(task, self._last_layout)
        if task:
            self._current_task_final_data[task] = (final_reply, layout)
        else:
            self._last_final_data = (final_reply, layout)
