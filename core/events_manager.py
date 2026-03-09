import asyncio
import json
import logging
from typing import AsyncGenerator

logger = logging.getLogger("quadlet-manager.events")

class EventPublisher:
    def __init__(self):
        self.queues = []

    def subscribe(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self.queues:
            self.queues.remove(q)

    async def publish(self, event_type: str, data: dict):
        message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        for q in self.queues:
            await q.put(message)

    async def event_generator(self, request) -> AsyncGenerator[str, None]:
        q = self.subscribe()
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await q.get()
                yield message
        finally:
            self.unsubscribe(q)

publisher = EventPublisher()
