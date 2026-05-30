import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Aggiungi la root del progetto al path per gli import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import psutil  # noqa: F401
except ModuleNotFoundError:
    sys.modules["psutil"] = SimpleNamespace(
        cpu_percent=lambda: 0.0,
        virtual_memory=lambda: SimpleNamespace(percent=0.0),
    )

from core.proactive_manager import CalendarChecker, ProactiveManager, SysMonitorChecker


@pytest.mark.asyncio
async def test_sys_monitor_checker():
    # Mock psutil per evitare dipendenze dall'hardware nel test
    with patch("psutil.cpu_percent", return_value=90.0), patch("psutil.virtual_memory") as mock_ram:
        mock_ram.return_value.percent = 50.0

        checker = SysMonitorChecker(cpu_threshold=80)
        result = await checker.check()
        assert "Allerta Sistema: Utilizzo CPU" in result


@pytest.mark.asyncio
async def test_proactive_loop_broadcast():
    from core.websocket_manager import manager

    mock_tm = MagicMock()
    # Mock del WebSocket manager
    with patch("core.websocket_manager.manager.broadcast", new_callable=AsyncMock) as mock_broadcast:
        pm = ProactiveManager(mock_tm, websocket_manager=manager, interval=0.1)

        # Mock di un checker che ritorna sempre un alert
        mock_checker = AsyncMock()
        mock_checker.check.return_value = "Test Alert"
        mock_checker.name = "Test"
        pm.checkers = [mock_checker]

        # Avviamo il loop per un breve istante
        task = asyncio.create_task(pm.start_loop())
        await asyncio.sleep(0.2)
        task.cancel()

        # Verifica che broadcast sia stato chiamato
        assert mock_broadcast.called
        args = mock_broadcast.call_args[0][0]
        assert args["type"] == "log"
        assert "Test Alert" in args["text"]


@pytest.mark.asyncio
async def test_proactive_loop_speaks_all_alerts():
    mock_tm = MagicMock()
    mock_voice = MagicMock()
    pm = ProactiveManager(mock_tm, interval=60, voice_manager=mock_voice)

    mock_checker = AsyncMock()
    mock_checker.check.return_value = "Test Alert"
    mock_checker.name = "Test"
    pm.checkers = [mock_checker]

    task = asyncio.create_task(pm.start_loop())
    await asyncio.sleep(0.1)
    task.cancel()

    mock_voice.speak.assert_called_with("Test Alert")
