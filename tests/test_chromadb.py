#!/usr/bin/env python3
"""Test ChromaDB + Ollama embeddings integration."""

import asyncio
import sys
import os

# Aggiungi la root del progetto al path per importare i moduli
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory_manager import MemoryManager


async def test():
    """Test ChromaDB initialization, add_turn, and semantic retrieval."""
    try:
        m = MemoryManager()
        print(f"[OK] ChromaDB initialized")
        print(f"   Collection: {m.collection.name}")
        print(f"   Count: {m.collection.count()}")
        
        # Test add_turn with embedding
        print("\n[STEP] Adding turn to memory...")
        await m.add_turn("user", "Qual è il prezzo del Bitcoin?")
        print(f"[OK] Turn aggiunto. Nuovi count: {m.collection.count()}")
        
        # Test semantic retrieval
        print("\n[STEP] Testing semantic retrieval...")
        context = await m.get_context("Bitcoin", top_k=3)
        print(f"[OK] Retrieval result:")
        print(context)
        
        # Test multiple turns
        print("\n[STEP] Adding more turns...")
        await m.add_turn("jarvis", "Il prezzo dipende dal mercato.")
        await m.add_turn("user", "Parlammo di questo a marzo?")
        print(f"[OK] Turns added. Total: {m.collection.count()}")
        
        # Test historical retrieval
        print("\n[STEP] Testing historical query...")
        historical = await m.get_context("marzo riunione", top_k=5)
        print(f"[OK] Historical retrieval:")
        print(historical)
        
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test())
