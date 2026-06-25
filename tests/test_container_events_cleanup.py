import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from services.container_events import container_events_cleanup_loop

@pytest.mark.asyncio
async def test_container_events_cleanup_loop_runs_and_cancels():
    with patch("services.container_events.asyncio.sleep") as mock_sleep, \
         patch("services.container_events.cleanup_old_events") as mock_cleanup:
        
        # Make the sleep raise CancelledError after first iteration
        mock_sleep.side_effect = [None, asyncio.CancelledError()]
        
        try:
            await container_events_cleanup_loop()
        except asyncio.CancelledError:
            pass
            
        assert mock_cleanup.call_count == 1

@pytest.mark.asyncio
async def test_container_events_cleanup_loop_handles_exception():
    with patch("services.container_events.asyncio.sleep") as mock_sleep, \
         patch("services.container_events.cleanup_old_events") as mock_cleanup:
        
        # Make the cleanup raise an Exception, and the next sleep raise CancelledError
        mock_cleanup.side_effect = Exception("Test Exception")
        mock_sleep.side_effect = [None, asyncio.CancelledError()]
        
        try:
            await container_events_cleanup_loop()
        except asyncio.CancelledError:
            pass
            
        assert mock_cleanup.call_count == 1
