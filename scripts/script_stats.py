import asyncio
import logging
import os
import sys

logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.stats_engine import fetch_server_stats
from core.events_manager import publisher
from core.database import init_db

async def test():
    await init_db()
    q = publisher.subscribe()
    
    # Run fetch. Keep the reference: a bare create_task() can be collected
    # before it runs, and then the wait_for below always times out.
    fetch_task = asyncio.create_task(fetch_server_stats())

    try:
        msg = await asyncio.wait_for(q.get(), timeout=30.0)
        print("Event:", msg)
    except asyncio.TimeoutError:
        print("No event received")
    finally:
        fetch_task.cancel()

asyncio.run(test())
