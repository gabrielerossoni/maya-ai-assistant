import sys
import os
import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch

# Aggiungi la root del progetto al path per gli import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent_core import AgentCore

@pytest.fixture
def agent():
    return AgentCore()

@pytest.mark.asyncio
async def test_react_loop_logic(agent):
    # Mock dell'LLM (ollama)
    with patch("core.agent_core.is_ollama_enabled", return_value=True), \
         patch.object(agent, "_call_groq", new_callable=AsyncMock, return_value=None), \
         patch("ollama.AsyncClient.chat", new_callable=AsyncMock) as mock_chat, \
         patch.object(agent, "_route_intent", return_value="domotic"), \
         patch.object(agent.tool_manager, "execute", new_callable=AsyncMock) as mock_execute:
        
        # Il tool "weather" è nella lista needs_rephrase, quindi il ReAct loop
        # fa 2 step: primo chiama il tool, secondo riformula i dati in linguaggio naturale.
        mock_chat.side_effect = [
            # Primo step: chiama tool weather
            {
                "message": {
                    "content": json.dumps({
                        "thought": "Devo controllare il meteo.",
                        "actions": [{"tool": "weather", "location": "Milano"}],
                        "reply": "Controllo il meteo..."
                    })
                }
            },
            # Secondo step: riformula i dati del tool in risposta naturale
            {
                "message": {
                    "content": json.dumps({
                        "thought": "Ho i dati, ora rispondo.",
                        "actions": [],
                        "reply": "A Milano c'è il sole, 20 gradi."
                    })
                }
            }
        ]
        
        mock_execute.return_value = {"status": "ok", "message": "Soleggiato, 20 gradi"}
        
        response_tokens = []
        async for token in agent.process("Com'è il meteo a Milano?"):
            response_tokens.append(token)
        response = "".join(response_tokens)
        
        # La frase pre ("Controllo il meteo...") è streamata come primo token,
        # poi il secondo step riformula i dati meteo in linguaggio naturale
        assert "Controllo il meteo..." in response
        assert "A Milano c'è il sole" in response
        assert mock_execute.call_count == 1
        # 2 chiamate LLM: prima per decidere il tool, seconda per riformulare
        assert mock_chat.call_count == 2
