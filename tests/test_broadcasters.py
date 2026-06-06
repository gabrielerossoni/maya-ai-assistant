from types import SimpleNamespace

import pytest

import core.broadcasters as broadcasters


@pytest.mark.asyncio
async def test_broadcast_state_offloads_gpu_stats(monkeypatch):
    calls = []

    async def fake_models_status(_models):
        return {}

    async def fake_to_thread(func, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(broadcasters, "get_models_status", fake_models_status)
    monkeypatch.setattr(broadcasters.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(broadcasters, "get_gpu_stats", lambda: {"gpu_available": False})
    monkeypatch.setattr(broadcasters, "_last_models_check", 0)
    monkeypatch.setattr(broadcasters, "_cached_models_status", {})

    payloads = []
    manager = SimpleNamespace(broadcast=lambda payload: payloads.append(payload))

    async def broadcast(payload):
        payloads.append(payload)

    manager.broadcast = broadcast
    agent = SimpleNamespace(
        tool_manager=SimpleNamespace(tools={}),
        memory=SimpleNamespace(turns=[]),
    )

    await broadcasters.broadcast_state(agent, manager, {})

    assert calls == [broadcasters.get_gpu_stats]
    assert payloads and payloads[0]["gpu_available"] is False
