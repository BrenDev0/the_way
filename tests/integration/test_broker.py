"""The task queue against a real Redis: a running message is renewed and never taken
back, a dead worker's is, and a read takes one message only. Timings are scaled down
(idle 1 s, heartbeat 0.25 s) on a stream of the test's own."""

import asyncio
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from src.core.settings import settings
from src.core.tasks.broker import HeartbeatStreamBroker

IDLE_MS = 1000


def make_broker(stream: str) -> HeartbeatStreamBroker:
    return HeartbeatStreamBroker(
        url=settings.TASKIQ_BROKER_URL,
        queue_name=stream,
        consumer_group_name=f"{stream}:group",
        consumer_id="0",
        xread_block=200,
        xread_count=1,
        idle_timeout=IDLE_MS,
        heartbeat=0.25,
        heartbeat_max=60,
    )


@pytest.fixture
async def stream():
    name = f"test:broker:{uuid4()}"
    yield name
    async with Redis.from_url(settings.TASKIQ_BROKER_URL) as redis:
        await redis.delete(name)


async def add(stream: str, *payloads: bytes) -> None:
    async with Redis.from_url(settings.TASKIQ_BROKER_URL) as redis:
        for payload in payloads:
            await redis.xadd(stream, {b"data": payload})


async def pending(stream: str) -> list[dict]:
    async with Redis.from_url(settings.TASKIQ_BROKER_URL) as redis:
        return await redis.xpending_range(stream, f"{stream}:group", min="-", max="+", count=10)


async def take(broker: HeartbeatStreamBroker, timeout: float = 5):
    listening = broker.listen()
    return await asyncio.wait_for(anext(listening), timeout), listening


async def test_a_long_running_message_is_renewed_and_not_taken_back(stream):
    worker, other = make_broker(stream), make_broker(stream)
    await worker.startup()
    await other.startup()
    await add(stream, b"turn")
    message, _ = await take(worker)

    await asyncio.sleep(IDLE_MS / 1000 * 2.5)  # well past the idle timeout, still running

    held = await pending(stream)
    assert len(held) == 1
    assert held[0]["consumer"].decode() == worker.consumer_name
    assert held[0]["time_since_delivered"] < IDLE_MS
    # another worker reading now does not get it a second time
    with pytest.raises(TimeoutError):
        await take(other, timeout=1.5)

    await message.ack()
    assert await pending(stream) == []
    await worker.shutdown()
    await other.shutdown()


async def test_a_dead_workers_message_comes_back(stream):
    dead, alive = make_broker(stream), make_broker(stream)
    await dead.startup()
    await alive.startup()
    await add(stream, b"turn")
    await take(dead)
    for beat in list(dead._beats):  # the process died: nothing renews it any more
        beat.cancel()

    await asyncio.sleep(IDLE_MS / 1000 * 1.5)
    # the next read finds nothing new, then takes back what went idle
    await add(stream, b"nudge")
    first, listening = await take(alive)
    second = await asyncio.wait_for(anext(listening), 5)

    assert {first.data, second.data} == {b"turn", b"nudge"}
    await first.ack()
    await second.ack()
    await dead.shutdown()
    await alive.shutdown()


async def test_a_read_takes_one_message_not_a_batch(stream):
    worker = make_broker(stream)
    await worker.startup()
    await add(stream, b"a", b"b", b"c")

    message, _ = await take(worker)

    assert len(await pending(stream)) == 1  # b and c are still in the stream for anyone
    await message.ack()
    await worker.shutdown()
