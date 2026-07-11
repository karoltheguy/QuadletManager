import asyncio
import json
import logging
from typing import AsyncGenerator

logger = logging.getLogger("quadlet-manager.events")

class EventPublisher:
    def __init__(self):
        """Initialize the EventPublisher with an empty list of subscriber queues."""
        self.queues = []

    def subscribe(self, maxsize: int = 0) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=maxsize)
        self.queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        if q in self.queues:
            self.queues.remove(q)

    async def publish(self, event_type: str, data: dict):
        message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        for q in self.queues:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                q.put_nowait(message)

    async def event_generator(self, request, maxsize=200) -> AsyncGenerator[str, None]:
        q = self.subscribe(maxsize=maxsize)
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await q.get()
                yield message
        finally:
            self.unsubscribe(q)

publisher = EventPublisher()
