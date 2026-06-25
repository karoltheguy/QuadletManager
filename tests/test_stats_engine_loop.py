import pytest
import asyncio
import time
from unittest.mock import patch, AsyncMock
from services.stats_engine import stats_engine_loop

@pytest.mark.asyncio
async def test_stats_engine_loop_runs_and_cancels():
    with patch("services.stats_engine.asyncio.sleep") as mock_sleep, \
         patch("services.stats_engine.fetch_server_stats") as mock_fetch, \
         patch("services.stats_engine.rollup_health_history") as mock_rollup, \
         patch("services.stats_engine._last_rollup_time", time.time() - 3600):
        
        # Make the sleep raise CancelledError after first iteration
        mock_sleep.side_effect = [None, asyncio.CancelledError()]
        
        try:
            await stats_engine_loop()
        except asyncio.CancelledError:
            pass
            
        assert mock_fetch.call_count == 1
        assert mock_rollup.call_count == 1

@pytest.mark.asyncio
async def test_stats_engine_loop_handles_exception():
    with patch("services.stats_engine.asyncio.sleep") as mock_sleep, \
         patch("services.stats_engine.fetch_server_stats") as mock_fetch:
        
        # Make the fetch raise an Exception, and the next sleep raise CancelledError
        mock_fetch.side_effect = Exception("Test Exception")
        mock_sleep.side_effect = [None, asyncio.CancelledError()]
        
        try:
            await stats_engine_loop()
        except asyncio.CancelledError:
            pass
            
        assert mock_fetch.call_count == 1
