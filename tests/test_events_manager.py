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
async def test_stats_update_filtered_by_server_id_other_events_broadcast(publisher):
    q1 = publisher.subscribe(server_id=1)
    q2 = publisher.subscribe(server_id=2)
    q_all = publisher.subscribe()

    await publisher.publish("stats_update", {"server_id": 1, "foo": "bar"})

    assert q1.qsize() > 0
    with pytest.raises(asyncio.QueueEmpty):
        q2.get_nowait()
    assert q_all.qsize() > 0

    # drain q1 and q_all so the next assertions are unambiguous
    await q1.get()
    await q_all.get()

    await publisher.publish("poll_health", {"server_id": 1, "healthy": True})

    msg1 = await q1.get()
    msg2 = await q2.get()
    msg_all = await q_all.get()

    expected = f"event: poll_health\ndata: {json.dumps({'server_id': 1, 'healthy': True})}\n\n"
    assert msg1 == expected
    assert msg2 == expected
    assert msg_all == expected

@pytest.mark.asyncio
@pytest.mark.unit
async def test_event_generator_threads_server_id_through_to_filtering(publisher):
    mock_request1 = AsyncMock()
    mock_request1.is_disconnected.side_effect = [False, True]
    mock_request2 = AsyncMock()
    mock_request2.is_disconnected.side_effect = [False, True]

    gen1 = publisher.event_generator(mock_request1, server_id=1)
    gen2 = publisher.event_generator(mock_request2, server_id=2)

    # Step gen2 in the background so it subscribes (creating its queue) and
    # then blocks on q.get(), just like a real client connection would.
    gen2_task = asyncio.create_task(anext(gen2))

    async def push_event():
        await asyncio.sleep(0.01)
        await publisher.publish("stats_update", {"server_id": 1, "cpu": 42})

    asyncio.create_task(push_event())

    # gen1 (server_id=1) should receive the matching stats_update
    msg = await anext(gen1)
    assert "event: stats_update" in msg
    assert '"server_id": 1' in msg

    # gen1 finishes on second iteration (is_disconnected=True)
    with pytest.raises(StopAsyncIteration):
        await anext(gen1)

    # Let the push_event task and gen2's subscription settle.
    await asyncio.sleep(0.02)

    # gen2 (server_id=2) should never have received the stats_update for
    # server_id=1. Confirm directly via its underlying queue (rather than
    # awaiting gen2_task, which would block forever on an empty queue).
    server_id_2_queues = [q for q in publisher.queues if publisher._server_ids.get(id(q)) == 2]
    assert len(server_id_2_queues) == 1
    assert server_id_2_queues[0].qsize() == 0

    # Clean up gen2 so it doesn't leak a task/queue.
    gen2_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await gen2_task
    await gen2.aclose()
    assert len(publisher.queues) == 0
