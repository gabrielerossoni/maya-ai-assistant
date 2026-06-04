import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Aggiungi la root del progetto al path per gli import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent_core import AgentCore


@pytest.fixture
def agent():
    return AgentCore()


def test_hard_route_light_room_color_without_verb(agent):
    action = agent._hard_route_light_command("Luce Giardino Fucsia")

    assert action == {
        "tool": "arduino",
        "op": "SET",
        "target": "rgb3",
        "value": {"r": 255, "g": 0, "b": 255},
        "effect": 0,
    }


def test_hard_route_light_compound_color_uses_exact_room_target(agent):
    action = agent._hard_route_light_command("luce fuori nero mezzanotte")

    assert action == {
        "tool": "arduino",
        "op": "SET",
        "target": "rgb3",
        "value": {"r": 0, "g": 0, "b": 20},
        "effect": 0,
    }


def test_hard_route_garden_brown_does_not_target_all_rgb(agent):
    action = agent._hard_route_light_command("luci giardino marrone")

    assert action == {
        "tool": "arduino",
        "op": "SET",
        "target": "rgb3",
        "value": {"r": 120, "g": 70, "b": 35},
        "effect": 0,
    }


def test_hard_route_outside_green_plural_uses_rgb3(agent):
    action = agent._hard_route_light_command("luci fuori verdi")

    assert action == {
        "tool": "arduino",
        "op": "SET",
        "target": "rgb3",
        "value": {"r": 0, "g": 255, "b": 153},
        "effect": 0,
    }


def test_hard_route_turns_off_all_lights_without_room(agent):
    action = agent._hard_route_light_command("spegni luci")

    assert action == {
        "tool": "arduino",
        "op": "BATCH",
        "actions": [
            {"op": "SET", "target": "light", "value": 0},
            {"op": "SET", "target": "rgb", "value": 0, "effect": 0},
            {"op": "SET", "target": "neopixel", "value": 0, "effect": 0},
        ],
    }


def test_hard_route_wake_light_on_defaults_to_visible_white(agent):
    action = agent._hard_route_light_command("Maya, accendi la luce")

    assert action == {
        "tool": "arduino",
        "op": "BATCH",
        "actions": [
            {"op": "SET", "target": "light", "value": 1},
            {"op": "SET", "target": "rgb", "value": {"r": 255, "g": 255, "b": 255}, "effect": 0},
        ],
    }


def test_react_arduino_rgb_action_is_scoped_to_requested_room(agent):
    action = agent._normalize_arduino_action_for_request(
        {"tool": "arduino", "op": "SET", "target": "rgb", "value": {"r": 120, "g": 70, "b": 35}},
        "luci giardino marrone",
    )

    assert action["target"] == "rgb3"


@pytest.mark.asyncio
async def test_process_hard_routes_light_before_automation(agent):
    agent.memory.add_turn = AsyncMock()
    agent.tool_manager.execute = AsyncMock(return_value={"status": "ok", "state": {"rgb3": [0, 0, 20]}})

    tokens = []
    async for token in agent.process("luce fuori nero mezzanotte"):
        tokens.append(token)

    action = agent.tool_manager.execute.call_args.args[0]
    assert action["target"] == "rgb3"
    assert action["value"] == {"r": 0, "g": 0, "b": 20}
    assert "scena" not in "".join(tokens).lower()


@pytest.mark.asyncio
async def test_process_wake_light_on_uses_direct_visible_white_batch(agent):
    agent.memory.add_turn = AsyncMock()
    agent.tool_manager.execute = AsyncMock(return_value={"status": "ok", "state": {"light": True}})

    tokens = []
    async for token in agent.process("maya accendi la luce"):
        tokens.append(token)

    action = agent.tool_manager.execute.call_args.args[0]
    assert action == {
        "tool": "arduino",
        "op": "BATCH",
        "actions": [
            {"op": "SET", "target": "light", "value": 1},
            {"op": "SET", "target": "rgb", "value": {"r": 255, "g": 255, "b": 255}, "effect": 0},
        ],
    }
    assert "".join(tokens).strip() == "Luce accesa."


@pytest.mark.asyncio
async def test_process_direct_weather_phrase_calls_weather_tool(agent):
    agent.memory.add_turn = AsyncMock()
    agent.tool_manager.execute = AsyncMock(
        return_value={
            "status": "ok",
            "data": {
                "location": "Roma",
                "temp": 24.2,
                "condition": "Sereno",
                "wind": 8.0,
                "daily": [],
                "hourly": [],
            },
        }
    )

    tokens = []
    async for token in agent.process("che tempo fa"):
        tokens.append(token)

    assert agent.tool_manager.execute.call_args.args[0] == {"tool": "weather", "location": None}
    response = "".join(tokens)
    assert "A Roma" in response
    assert "24 gradi" in response


@pytest.mark.asyncio
async def test_process_direct_weather_phrase_extracts_location(agent):
    agent.memory.add_turn = AsyncMock()
    agent.tool_manager.execute = AsyncMock(
        return_value={
            "status": "ok",
            "data": {
                "location": "Milano",
                "temp": 19,
                "condition": "Nuvoloso",
                "wind": None,
                "daily": [],
                "hourly": [],
            },
        }
    )

    tokens = []
    async for token in agent.process("che tempo fa a Milano"):
        tokens.append(token)

    assert agent.tool_manager.execute.call_args.args[0] == {"tool": "weather", "location": "Milano"}
    assert "A Milano" in "".join(tokens)


def test_direct_weather_does_not_steal_home_sensor_temperature(agent):
    agent = AgentCore()

    assert agent._parse_direct_weather_command("temperatura casa") is None


@pytest.mark.asyncio
async def test_process_stop_alarm_accepts_alarme_misrecognition(agent):
    agent.memory.add_turn = AsyncMock()
    agent._stop_alarm_direct = AsyncMock(return_value="Allarme fermato.")

    tokens = []
    async for token in agent.process("ferma alarme"):
        tokens.append(token)

    agent._stop_alarm_direct.assert_awaited_once()
    assert "".join(tokens) == "Allarme fermato."


@pytest.mark.asyncio
async def test_process_stop_alarm_accepts_apostrophe_misrecognition(agent):
    agent.memory.add_turn = AsyncMock()
    agent._stop_alarm_direct = AsyncMock(return_value="Allarme fermato.")

    tokens = []
    async for token in agent.process("spegni all'armi"):
        tokens.append(token)

    agent._stop_alarm_direct.assert_awaited_once()
    assert "".join(tokens) == "Allarme fermato."


@pytest.mark.asyncio
async def test_react_does_not_repeat_action_reply(agent):
    reply = "Ho aggiornato il dispositivo."
    agent.memory.add_turn = AsyncMock()
    agent.memory.get_context = AsyncMock(return_value="")

    with (
        patch("core.agent_core.is_ollama_enabled", return_value=True),
        patch.object(agent, "_call_groq", new_callable=AsyncMock, return_value=None),
        patch("ollama.AsyncClient.chat", new_callable=AsyncMock) as mock_chat,
        patch.object(agent, "_route_intent", return_value="DOMOTIC"),
        patch.object(agent.tool_manager, "execute", new_callable=AsyncMock) as mock_execute,
    ):
        mock_chat.return_value = {
            "message": {
                "content": json.dumps(
                    {
                        "thought": "Devo usare un tool.",
                        "actions": [{"tool": "arduino", "op": "SET", "target": "rgb3", "value": 0}],
                        "reply": reply,
                    }
                )
            }
        }
        mock_execute.return_value = {"status": "ok", "message": "ok"}

        response_tokens = []
        async for token in agent.process("controlla dispositivo"):
            response_tokens.append(token)

    assert "".join(response_tokens).count(reply) == 1
    assert mock_execute.call_count == 1


@pytest.mark.asyncio
async def test_react_loop_logic(agent):
    # Mock dell'LLM (ollama)
    with (
        patch("core.agent_core.is_ollama_enabled", return_value=True),
        patch.object(agent, "_call_groq", new_callable=AsyncMock, return_value=None),
        patch("ollama.AsyncClient.chat", new_callable=AsyncMock) as mock_chat,
        patch.object(agent, "_route_intent", return_value="domotic"),
        patch.object(agent.tool_manager, "execute", new_callable=AsyncMock) as mock_execute,
    ):
        # Il tool "weather" è nella lista needs_rephrase, quindi il ReAct loop
        # fa 2 step: primo chiama il tool, secondo riformula i dati in linguaggio naturale.
        mock_chat.side_effect = [
            # Primo step: chiama tool weather
            {
                "message": {
                    "content": json.dumps(
                        {
                            "thought": "Devo controllare il meteo.",
                            "actions": [{"tool": "weather", "location": "Milano"}],
                            "reply": "Controllo il meteo...",
                        }
                    )
                }
            },
            # Secondo step: riformula i dati del tool in risposta naturale
            {
                "message": {
                    "content": json.dumps(
                        {
                            "thought": "Ho i dati, ora rispondo.",
                            "actions": [],
                            "reply": "A Milano c'è il sole, 20 gradi.",
                        }
                    )
                }
            },
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


@pytest.mark.asyncio
async def test_react_default_max_steps_is_two(agent, monkeypatch):
    agent.memory.add_turn = AsyncMock()
    agent.memory.get_context = AsyncMock(return_value="")
    monkeypatch.delenv("REACT_MAX_STEPS", raising=False)

    with (
        patch("core.agent_core.is_ollama_enabled", return_value=True),
        patch.object(agent, "_call_groq", new_callable=AsyncMock, return_value=None),
        patch("ollama.AsyncClient.chat", new_callable=AsyncMock) as mock_chat,
        patch.object(agent, "_route_intent", return_value="REASONING"),
        patch.object(agent.tool_manager, "execute", new_callable=AsyncMock) as mock_execute,
    ):
        mock_chat.return_value = {
            "message": {
                "content": json.dumps(
                    {
                        "thought": "Continuo a usare tool.",
                        "actions": [{"tool": "weather", "location": "Milano"}],
                        "reply": "Controllo...",
                    }
                )
            }
        }
        mock_execute.return_value = {"status": "ok", "message": "ok"}

        response_tokens = []
        async for token in agent.process("chi e Brad Pitt?"):
            response_tokens.append(token)

    assert mock_chat.call_count == 2
    assert "troppi passaggi" in "".join(response_tokens)


@pytest.mark.asyncio
async def test_react_rate_limit_returns_voice_reply(agent):
    agent = AgentCore()
    agent.memory.add_turn = AsyncMock()
    agent.memory.get_context = AsyncMock(return_value="")

    async def fake_groq(*args, **kwargs):
        agent._last_groq_error_status = 429
        return None

    with (
        patch("core.agent_core.is_ollama_enabled", return_value=False),
        patch.object(agent, "_call_groq", side_effect=fake_groq),
        patch.object(agent, "_route_intent", return_value="REASONING"),
    ):
        response_tokens = []
        async for token in agent.process("chi e Brad Pitt?"):
            response_tokens.append(token)

    assert "limite di richieste" in "".join(response_tokens)
