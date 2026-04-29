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

MEMORY_DIR = "data"
METADATA_FILE = os.path.join(MEMORY_DIR, "memory_metadata.json")
CHROMA_PERSIST_DIR = os.path.join(MEMORY_DIR, "chroma_db")
EMBEDDING_MODEL = "nomic-embed-text"  # Via Ollama


class MemoryManager:
    """Memoria semantica con vector database ChromaDB."""

    def __init__(self):
        self.turns = []  # Cache in-memory di tutti i turni
        self.save_lock = asyncio.Lock()
        self.chroma_client = None
        self.collection = None
        self._init_chroma()

    def _init_chroma(self):
        """Inizializza ChromaDB con persistenza su disco."""
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
        
        # Settings con persistenza
        settings = Settings(
            chroma_db_impl="duckdb+parquet",
            persist_directory=CHROMA_PERSIST_DIR,
            anonymized_telemetry=False,
        )
        
        self.chroma_client = chromadb.Client(settings)
        
        # Crea o recupera collection
        try:
            self.collection = self.chroma_client.get_collection(
                name="jarvis_memory",
                metadata={"hnsw:space": "cosine"}
            )
        except:
            self.collection = self.chroma_client.create_collection(
                name="jarvis_memory",
                metadata={"hnsw:space": "cosine"}
            )

    def load(self):
        """Carica memoria da file JSON (metadata + ChromaDB)."""
        os.makedirs(MEMORY_DIR, exist_ok=True)
        
        if os.path.exists(METADATA_FILE):
            with open(METADATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.turns = data.get("turns", [])
                print(f"[MEMORY] {len(self.turns)} turni caricati dalla memoria semantica.")
        else:
            self.turns = []
            print("[MEMORY] Nuova memoria inizializzata.")

    async def save(self):
        """Salva metadata su JSON (embeddings già in ChromaDB)."""
        async with self.save_lock:
            os.makedirs(MEMORY_DIR, exist_ok=True)
            with open(METADATA_FILE, "w", encoding="utf-8") as f:
                json.dump({"turns": self.turns}, f, ensure_ascii=False, indent=2)

    async def _get_embedding(self, text: str) -> Optional[list]:
        """Ottieni embedding da Ollama (nomic-embed-text)."""
        try:
            import ollama
            client = ollama.AsyncClient()
            response = await client.embed(
                model=EMBEDDING_MODEL,
                input=text
            )
            return response.get("embeddings", [None])[0]
        except Exception as e:
            print(f"[MEMORY] Errore embedding: {e}")
            return None

    async def add_turn(self, role: str, text: str):
        """Aggiunge un turno alla memoria con embedding semantico."""
        turn = {
            "role": role,
            "text": text,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.turns.append(turn)
        
        # Calcola embedding e aggiungilo a ChromaDB
        embedding = await self._get_embedding(text)
        if embedding:
            turn_id = f"{role}_{len(self.turns)}_{int(datetime.now().timestamp() * 1000)}"
            self.collection.add(
                ids=[turn_id],
                documents=[text],
                metadatas=[{"role": role, "time": turn.get("time")}],
                embeddings=[embedding]
            )
        
        await self.save()

    async def get_context(self, query: Optional[str] = None, top_k: int = 5) -> str:
        """
        Recupera contesto rilevante.
        Se query è fornita, usa retrieval semantico.
        Altrimenti torna gli ultimi messaggi (fallback).
        """
        if not query or not self.collection.count() > 0:
            # Fallback: ultimi 5 turni
            recent = self.turns[-5:] if self.turns else []
            context = "\n".join(
                f"[{t['time']}] {t['role'].upper()}: {t['text'][:100]}..."
                for t in recent
            )
            return f"Contesto recente:\n{context}" if context else "Memoria vuota."
        
        # Retrieval semantico
        try:
            embedding = await self._get_embedding(query)
            if not embedding:
                return "Impossibile recuperare contesto (embedding fallito)."
            
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=top_k
            )
            
            # Formatta risultati
            if results and results.get("documents"):
                context = "\n".join(
                    f"- {doc[:80]}..." for doc in results["documents"][0]
                )
                return f"Contesto rilevante:\n{context}"
            else:
                return "Nessun contesto rilevante trovato."
        except Exception as e:
            print(f"[MEMORY] Errore retrieval: {e}")
            return f"Errore nel recupero del contesto: {e}"

    async def get_all(self) -> list:
        """Ritorna tutti i turni (per export/debug)."""
        return self.turns

    async def search(self, query: str, top_k: int = 10) -> list:
        """Cerca messaggi rilevanti per una query."""
        try:
            embedding = await self._get_embedding(query)
            if not embedding:
                return []
            
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=top_k
            )
            
            if results and results.get("documents"):
                return results["documents"][0]
            return []
        except Exception as e:
            print(f"[MEMORY] Errore search: {e}")
            return []
