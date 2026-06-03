import asyncio
import os
import sys
from unittest.mock import AsyncMock

# Aggiungi la root del progetto al path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.agent_core import AgentCore


@pytest.mark.asyncio
async def test_knowledge_questions_are_not_chitchat(monkeypatch):
    agent = AgentCore()
    monkeypatch.setattr(agent, "_llm_routing", AsyncMock(return_value="CHITCHAT"))

    assert await agent._route_intent_uncached("che è Brad Pitt?") == "REASONING"
    assert await agent._route_intent_uncached("dimmi chi è Brad Pitt.") == "REASONING"
    assert await agent._route_intent_uncached("che è Napoleone.") == "REASONING"
    assert await agent._route_intent_uncached("ciao Maya") == "CHITCHAT"


@pytest.mark.asyncio
async def test_llm_chitchat_is_rejected_for_non_social_input(monkeypatch):
    agent = AgentCore()
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setattr(agent, "_call_groq", AsyncMock(return_value="CHITCHAT"))

    assert await agent._llm_routing("dimmi qualcosa su Brad Pitt") == "REASONING"


@pytest.mark.asyncio
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
