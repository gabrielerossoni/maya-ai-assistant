"""
memory_manager.py
Memoria semantica con ChromaDB + Ollama embeddings.
Sostituisce il lineare memory.json — recupera contesto rilevante da mesi di conversazioni.
"""

import json
import os
import asyncio
from datetime import datetime
from typing import Optional
import chromadb
from chromadb.config import Settings
import httpx

MEMORY_DIR = "data"
METADATA_FILE = os.path.join(MEMORY_DIR, "memory_metadata.json")
CHROMA_PERSIST_DIR = os.path.join(MEMORY_DIR, "chroma_db")
SUMMARIES_FILE = os.path.join(MEMORY_DIR, "memory_summaries.json")
EMBEDDING_MODEL = "nomic-embed-text"  # Via Ollama
_ollama_available = True  # Set to False after first connection failure to suppress repeated errors

_SUMMARY_TOPICS = {
    "domotica": ["luce", "relay", "servo", "accendi", "spegni", "arduino", "mqtt", "rgb", "buzzer"],
    "meteo": ["meteo", "temperatura", "piogge", "vento", "previsioni", "umidità", "clima"],
    "calendario": ["evento", "riunione", "appuntamento", "calendario", "promemoria", "scadenza"],
}


class MemoryManager:
    """Memoria semantica con vector database ChromaDB."""

    def __init__(self):
        self.turns = []  # Cache in-memory di tutti i turni
        self.save_lock = asyncio.Lock()
        self.turn_lock = asyncio.Lock()
        self.chroma_client = None
        self.collection = None
        self._init_chroma()

    def _init_chroma(self):
        """Inizializza ChromaDB con persistenza su disco."""
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
        
        try:
            # Nuovo client persistente (ChromaDB 0.4+)
            self.chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)
            
            # Crea o recupera collection
            self.collection = self.chroma_client.get_or_create_collection(
                name="jarvis_memory",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as e:
            print(f"[MEMORY] Errore inizializzazione ChromaDB: {e}")
            # Fallback o gestione errore silenziosa per non bloccare l'agente
            self.collection = None

    def load(self):
        """Carica memoria da file JSON (metadata + ChromaDB)."""
        os.makedirs(MEMORY_DIR, exist_ok=True)
        
        if os.path.exists(METADATA_FILE):
            try:
                with open(METADATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.turns = data.get("turns", [])
                    if len(self.turns) > 0:
                        print(f"[MEMORY] {len(self.turns)} turni in memoria.")
            except Exception as e:
                print(f"[MEMORY] Errore caricamento metadati: {e}")
                self.turns = []
        else:
            self.turns = []


    async def save(self):
        """Salva metadata su JSON."""
        async with self.save_lock:
            os.makedirs(MEMORY_DIR, exist_ok=True)
            try:
                with open(METADATA_FILE, "w", encoding="utf-8") as f:
                    json.dump({"turns": self.turns}, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[MEMORY] Errore salvataggio metadati: {e}")

    async def _get_embedding(self, text: str) -> Optional[list]:
        """Ottieni embedding da Ollama (nomic-embed-text)."""
        global _ollama_available
        if not _ollama_available or not text.strip():
            return None
            
        try:
            import ollama
            client = ollama.AsyncClient()
            response = await client.embed(
                model=EMBEDDING_MODEL,
                input=text
            )
            embeddings = response.get("embeddings", [])
            if embeddings:
                return embeddings[0]
            return None
        except Exception:
            _ollama_available = False
            print(f"[MEMORY] Ollama non disponibile — embedding semantici disabilitati.")
            return None

    async def add_turn(self, role: str, text: str):
        """Aggiunge un turno alla memoria con embedding semantico."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        turn = {
            "role": role,
            "text": text,
            "time": timestamp,
        }
        
        async with self.turn_lock:
            self.turns.append(turn)

            if len(self.turns) > 200:   # ← era 1000, troppo per sessioni lunghe
                self.turns = self.turns[-200:]

            # Trigger summary periodico (ogni 50 turni, non-blocking)
            if len(self.turns) % 50 == 0:
                asyncio.create_task(self.build_topic_summaries())

            # Calcola embedding e aggiungilo a ChromaDB
            if self.collection:
                import random
                ts_ms = int(datetime.now().timestamp() * 1000)
                rnd = random.randint(100, 999)
                turn_id = f"{role}_{ts_ms}_{rnd}"
                embedding = await self._get_embedding(text)
                try:
                    if embedding:
                        self.collection.add(
                            ids=[turn_id],
                            documents=[text],
                            metadatas=[{"role": role, "time": timestamp}],
                            embeddings=[embedding]
                        )
                    else:
                        # Ollama non disponibile: ChromaDB usa all-MiniLM-L6-v2 integrato
                        self.collection.add(
                            ids=[turn_id],
                            documents=[text],
                            metadatas=[{"role": role, "time": timestamp}]
                        )
                except Exception as e:
                    print(f"[MEMORY] Errore aggiunta a ChromaDB: {e}")

            await self.save()

    def _load_summaries(self) -> dict:
        """Carica i summary per topic da disco."""
        if not os.path.exists(SUMMARIES_FILE):
            return {}
        try:
            with open(SUMMARIES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    async def _summarize_via_llm(self, topic: str, text: str) -> str:
        """Chiama Groq per riassumere preferenze/abitudini dell'utente su un topic."""
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return ""
        prompt = (
            f"Riassumi in massimo 3 frasi brevi le preferenze e abitudini dell'utente "
            f"riguardo '{topic}', basandoti su questi messaggi:\n{text}"
        )
        messages = [
            {"role": "system", "content": "Sei un assistente che sintetizza abitudini utente. Rispondi in italiano, massimo 3 frasi."},
            {"role": "user", "content": prompt},
        ]
        try:
            model = os.getenv("GROQ_ROUTER_MODEL", "llama-3.1-8b-instant")
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": model, "messages": messages, "temperature": 0.3, "max_tokens": 150},
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[MEMORY] Errore summary LLM ({topic}): {e}")
            return ""

    async def build_topic_summaries(self):
        """Ogni 50 turni, crea summary per topic via LLM e li salva in data/memory_summaries.json."""
        if not self.turns:
            return

        topics = {k: [] for k in _SUMMARY_TOPICS}
        topics["altro"] = []

        for turn in self.turns[-100:]:
            text_lower = turn["text"].lower()
            placed = False
            for topic, keywords in _SUMMARY_TOPICS.items():
                if any(k in text_lower for k in keywords):
                    topics[topic].append(turn["text"])
                    placed = True
                    break
            if not placed:
                topics["altro"].append(turn["text"])

        summaries = self._load_summaries()
        for topic, texts in topics.items():
            if texts:
                combined = "\n".join(texts[-20:])
                summary = await self._summarize_via_llm(topic, combined)
                if summary:
                    summaries[topic] = summary

        try:
            os.makedirs(MEMORY_DIR, exist_ok=True)
            with open(SUMMARIES_FILE, "w", encoding="utf-8") as f:
                json.dump(summaries, f, ensure_ascii=False, indent=2)
            print(f"[MEMORY] Summary gerarchici aggiornati ({len(summaries)} topic).")
        except Exception as e:
            print(f"[MEMORY] Errore salvataggio summary: {e}")

    async def get_context(self, query: Optional[str] = None, top_k: int = 5) -> str:
        """
        Recupera contesto rilevante.
        Se query è fornita, usa retrieval semantico.
        Altrimenti torna gli ultimi messaggi (fallback).
        """
        # Prepend profilo utente dai summary gerarchici
        summaries = self._load_summaries()
        profile_context = ""
        if summaries:
            profile_context = "=== PROFILO UTENTE (sintesi) ===\n"
            for topic, summary in summaries.items():
                profile_context += f"[{topic.upper()}]: {summary}\n"
            profile_context += "\n"

        # Sempre includere gli ultimi 3 messaggi per la coerenza immediata
        recent_turns = self.turns[-3:] if self.turns else []
        recent_context = ""
        if recent_turns:
            recent_context = "--- CONVERSAZIONE RECENTE ---\n"
            for t in recent_turns:
                recent_context += f"[{t['time']}] {t['role'].upper()}: {t['text']}\n"
        
        # Se non c'è query o database, torniamo solo il recente
        if not query or not self.collection or self.collection.count() == 0:
            base = recent_context if recent_context else "Memoria vuota."
            return f"{profile_context}{base}".strip()
        
        # Retrieval semantico per il passato remoto
        try:
            embedding = await self._get_embedding(query)
            if embedding:
                results = self.collection.query(
                    query_embeddings=[embedding],
                    n_results=top_k
                )
            else:
                # Fallback: ChromaDB usa il proprio embedding integrato
                results = self.collection.query(
                    query_texts=[query],
                    n_results=top_k
                )
            
            semantic_context = ""
            if results and results.get("documents") and results["documents"][0]:
                semantic_context = "--- CONTESTO PASSATO RILEVANTE ---\n"
                for i, doc in enumerate(results["documents"][0]):
                    metadata = results["metadatas"][0][i]
                    role = metadata.get("role", "unknown").upper()
                    time = metadata.get("time", "unknown")
                    semantic_context += f"[{time}] {role}: {doc}\n"
            
            return f"{profile_context}{semantic_context}\n{recent_context}".strip()
            
        except Exception as e:
            print(f"[MEMORY] Errore retrieval semantico: {e}")
            return f"{profile_context}{recent_context}".strip()

    async def migrate_json_to_chroma(self):
        """Reindicizza i turni JSON in ChromaDB se il database vettoriale è vuoto."""
        if not self.collection or not self.turns:
            return
        if self.collection.count() > 0:
            return

        print(f"[MEMORY] ChromaDB vuoto — reindicizzazione di {len(self.turns)} turni dal JSON...")
        imported = 0
        errors = 0
        for i, turn in enumerate(self.turns):
            text = turn.get("text", "").strip()
            if not text:
                continue
            role      = turn.get("role", "unknown")
            timestamp = turn.get("time", "")
            turn_id   = f"migrate_{role}_{i}"
            try:
                embedding = await self._get_embedding(text)
                if embedding:
                    self.collection.add(
                        ids=[turn_id],
                        documents=[text],
                        metadatas=[{"role": role, "time": timestamp}],
                        embeddings=[embedding]
                    )
                else:
                    self.collection.add(
                        ids=[turn_id],
                        documents=[text],
                        metadatas=[{"role": role, "time": timestamp}]
                    )
                imported += 1
            except Exception:
                errors += 1

        msg = f"[MEMORY] Migrazione completata: {imported} turni indicizzati"
        if errors:
            msg += f", {errors} saltati"
        print(msg)

    async def get_all(self) -> list:
        """Ritorna tutti i turni caricati."""
        return self.turns

    async def search(self, query: str, top_k: int = 10) -> list:
        """Cerca messaggi rilevanti per una query."""
        if not self.collection:
            return []
            
        try:
            embedding = await self._get_embedding(query)
            if embedding:
                results = self.collection.query(
                    query_embeddings=[embedding],
                    n_results=top_k
                )
            else:
                results = self.collection.query(
                    query_texts=[query],
                    n_results=top_k
                )
            
            if results and results.get("documents"):
                return results["documents"][0]
            return []
        except Exception as e:
            print(f"[MEMORY] Errore search: {e}")
            return []
