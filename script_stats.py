import asyncio
import logging
import sys

logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

from services.stats_engine import fetch_server_stats
from core.events_manager import publisher
from core.database import init_db

async def test():
    await init_db()
    q = publisher.subscribe()
    
    # Run fetch
    asyncio.create_task(fetch_server_stats())
    
    try:
        msg = await asyncio.wait_for(q.get(), timeout=30.0)
        print("Event:", msg)
    except asyncio.TimeoutError:
        print("No event received")

asyncio.run(test())
