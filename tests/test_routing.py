import sys
import os
import asyncio

# Aggiungi la root del progetto al path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent_core import AgentCore

async def test_routing():
    agent = AgentCore()
    await agent.initialize()
    
    test_queries = [
        ("Accendi la luce in cucina", "DOMOTIC"),
        ("Spiegami la teoria della relatività", "REASONING"),
        ("Scrivi una funzione Python che calcola il fattoriale", "CODING"),
        ("Ciao Maya, come stai oggi?", "CHITCHAT"),
        ("Che tempo fa a Roma?", "DOMOTIC"),
        ("Qual è la radice quadrata di 144?", "REASONING"),
    ]
    
    print("\n--- TEST ROUTING SPECIALISTI ---")
    for query, expected in test_queries:
        print(f"\nQuery: '{query}'")
        intent = await agent._route_intent(query)
        status = "[OK]" if intent == expected else "[FALLITO]"
        print(f"Intent rilevato: {intent} (Atteso: {expected}) {status}")

if __name__ == "__main__":
    asyncio.run(test_routing())
