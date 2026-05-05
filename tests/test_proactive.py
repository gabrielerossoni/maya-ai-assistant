import sys
import os
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

# Aggiungi la root del progetto al path per gli import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proactive_manager import ProactiveManager, SysMonitorChecker, CalendarChecker

@pytest.mark.asyncio
async def test_sys_monitor_checker():
    # Mock psutil per evitare dipendenze dall'hardware nel test
    with patch("psutil.cpu_percent", return_value=90.0), \
         patch("psutil.virtual_memory") as mock_ram:
        mock_ram.return_value.percent = 50.0
        
        checker = SysMonitorChecker(cpu_threshold=80)
        result = await checker.check()
        assert "Allerta Sistema: Utilizzo CPU" in result

@pytest.mark.asyncio
async def test_proactive_loop_broadcast():
    mock_tm = MagicMock()
    # Mock del WebSocket manager
    with patch("websocket_manager.manager.broadcast", new_callable=AsyncMock) as mock_broadcast:
        pm = ProactiveManager(mock_tm, interval=0.1)
        
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
