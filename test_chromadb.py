#!/usr/bin/env python3
"""Test ChromaDB + Ollama embeddings integration."""

import asyncio
from memory_manager import MemoryManager


async def test():
    """Test ChromaDB initialization, add_turn, and semantic retrieval."""
    try:
        m = MemoryManager()
        print(f"✅ ChromaDB initialized")
        print(f"   Collection: {m.collection.name}")
        print(f"   Count: {m.collection.count()}")
        
        # Test add_turn with embedding
        print("\n📝 Adding turn to memory...")
        await m.add_turn("user", "Qual è il prezzo del Bitcoin?")
        print(f"✅ Turn aggiunto. Nuovi count: {m.collection.count()}")
        
        # Test semantic retrieval
        print("\n🔍 Testing semantic retrieval...")
        context = await m.get_context("Bitcoin", top_k=3)
        print(f"✅ Retrieval result:")
        print(context)
        
        # Test multiple turns
        print("\n📝 Adding more turns...")
        await m.add_turn("jarvis", "Il prezzo dipende dal mercato.")
        await m.add_turn("user", "Parlammo di questo a marzo?")
        print(f"✅ Turns added. Total: {m.collection.count()}")
        
        # Test historical retrieval
        print("\n🔍 Testing historical query...")
        historical = await m.get_context("marzo riunione", top_k=5)
        print(f"✅ Historical retrieval:")
        print(historical)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test())
