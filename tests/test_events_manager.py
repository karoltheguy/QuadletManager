import asyncio
import pytest
from unittest.mock import AsyncMock
import json
from core.events_manager import EventPublisher

@pytest.fixture
def publisher():
    return EventPublisher()

@pytest.mark.unit
def test_subscribe_unsubscribe(publisher):
    q = publisher.subscribe()
    assert len(publisher.queues) == 1
    assert publisher.queues[0] == q

    publisher.unsubscribe(q)
    assert len(publisher.queues) == 0

    # Unsubscribe again should not error
    publisher.unsubscribe(q)

@pytest.mark.asyncio
@pytest.mark.unit
async def test_publish(publisher):
    q1 = publisher.subscribe()
    q2 = publisher.subscribe()
    
    await publisher.publish("test_event", {"key": "value"})
    
    msg1 = await q1.get()
    msg2 = await q2.get()
    
    expected = f"event: test_event\ndata: {json.dumps({'key': 'value'})}\n\n"
    assert msg1 == expected
    assert msg2 == expected

@pytest.mark.asyncio
@pytest.mark.unit
async def test_event_generator(publisher):
    mock_request = AsyncMock()
    mock_request.is_disconnected.side_effect = [False, True]
    
    gen = publisher.event_generator(mock_request)
    
    # We need to manually push a message to the newly created queue.
    # Since generator executes lazily, we first step into it.
    async def push_event():
        # wait a tiny bit to ensure the generator has subscribed
        await asyncio.sleep(0.01)
        await publisher.publish("my_event", {})

    asyncio.create_task(push_event())
    
    # First yield should get the event
    msg = await anext(gen)
    assert "event: my_event" in msg
    
    # Second iteration will see is_disconnected=True and stop
    with pytest.raises(StopAsyncIteration):
        await anext(gen)
    
    # And it should have unsubscribed!
    assert len(publisher.queues) == 0

@pytest.mark.asyncio
@pytest.mark.unit
async def test_publish_drops_oldest_when_queue_full(publisher):
    q = publisher.subscribe(maxsize=2)

    await publisher.publish("e", {"n": 1})
    await publisher.publish("e", {"n": 2})
    await publisher.publish("e", {"n": 3})

    assert q.qsize() <= 2

    msg1 = await q.get()
    msg2 = await q.get()

    expected1 = f"event: e\ndata: {json.dumps({'n': 2})}\n\n"
    expected2 = f"event: e\ndata: {json.dumps({'n': 3})}\n\n"
    assert msg1 == expected1
    assert msg2 == expected2

@pytest.mark.asyncio
@pytest.mark.unit
async def test_stats_update_broadcasts_to_all_subscribers(publisher):
    q1 = publisher.subscribe()
    q2 = publisher.subscribe()

    await publisher.publish("stats_update", {"server_id": 1, "foo": "bar"})

    msg1 = await q1.get()
    msg2 = await q2.get()

    expected = f"event: stats_update\ndata: {json.dumps({'server_id': 1, 'foo': 'bar'})}\n\n"
    assert msg1 == expected
    assert msg2 == expected
