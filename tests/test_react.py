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
        
        # Step 1: LLM decide di usare un tool
        mock_chat.side_effect = [
            # Primo step: chiama tool
            {
                "message": {
                    "content": json.dumps({
                        "thought": "Devo controllare il meteo.",
                        "actions": [{"tool": "weather", "location": "Milano"}],
                        "reply": "Controllo il meteo..."
                    })
                }
            },
            # Secondo step: fornisce risposta finale
            {
                "message": {
                    "content": json.dumps({
                        "thought": "Ho i dati, ora rispondo.",
                        "actions": [],
                        "reply": "A Milano c'è il sole."
                    })
                }
            }
        ]
        
        mock_execute.return_value = {"status": "ok", "message": "Soleggiato, 20 gradi"}
        
        response_tokens = []
        async for token in agent.process("Com'è il meteo a Milano?"):
            response_tokens.append(token)
        response = "".join(response_tokens)
        
        assert "A Milano c'è il sole" in response
        assert mock_execute.call_count == 1
        assert mock_chat.call_count == 2
