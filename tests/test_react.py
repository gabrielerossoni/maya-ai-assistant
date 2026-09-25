from unittest.mock import AsyncMock, patch

import pytest

from core.agent_core import AgentCore


@pytest.fixture
def agent():
    instance = AgentCore()
    instance.memory.add_turn = AsyncMock()
    instance.memory.get_context = AsyncMock(return_value="")
    return instance


@pytest.mark.asyncio
async def test_process_direct_weather(agent):
    agent.tool_manager.execute = AsyncMock(return_value={"status": "ok", "data": {"location": "Roma", "temp": 24, "condition": "Sereno"}})
    response = "".join([token async for token in agent.process("che tempo fa")])
    assert agent.tool_manager.execute.call_args.args[0] == {"tool": "weather", "location": None}
    assert "24 gradi" in response


@pytest.mark.asyncio
async def test_process_direct_news(agent):
    agent.tool_manager.execute = AsyncMock(return_value={"status": "ok", "message": "Ultime notizie."})
    response = "".join([token async for token in agent.process("dimmi le news")])
    assert response == "Ultime notizie."


@pytest.mark.asyncio
async def test_process_direct_knowledge(agent):
    agent.tool_manager.execute = AsyncMock(return_value={"status": "ok", "message": "Manzoni bio."})
    response = "".join([token async for token in agent.process("parlami di Manzoni")])
    assert response == "Manzoni bio."
    assert agent.tool_manager.execute.call_args.args[0] == {"tool": "search", "query": "Alessandro Manzoni"}


@pytest.mark.asyncio
async def test_process_calendar_list(agent):
    agent.tool_manager.execute = AsyncMock(return_value={"status": "ok", "message": "Nessun evento."})
    response = "".join([token async for token in agent.process("cos'ho nel calendario?")])
    assert response == "Nessun evento."


@pytest.mark.asyncio
async def test_process_stop_alarm(agent):
    agent._stop_alarm_direct = AsyncMock(return_value="Allarme fermato.")
    response = "".join([token async for token in agent.process("ferma alarme")])
    assert response == "Allarme fermato."


@pytest.mark.asyncio
async def test_react_executes_mqtt_action_once(agent):
    reply = "Ho aggiornato il dispositivo."
    agent.tool_manager.execute = AsyncMock(return_value={"status": "ok", "message": "ok"})
    with (
        patch("core.agent_core.is_ollama_enabled", return_value=True),
        patch("ollama.AsyncClient.chat", new_callable=AsyncMock) as chat,
        patch.object(agent, "_route_intent", return_value="DOMOTIC"),
    ):
        chat.return_value = {"message": {"content": '{"actions":[{"tool":"mqtt","room":"studio","device":"light","state":"on"}],"reply":"Ho aggiornato il dispositivo."}'}}
        response = "".join([token async for token in agent.process("accendi luce studio")])
    assert response.count(reply) == 1
    assert agent.tool_manager.execute.call_count == 1
