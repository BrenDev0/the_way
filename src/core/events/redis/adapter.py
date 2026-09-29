import json
from typing import Any

import redis.asyncio as redis
from redis.exceptions import RedisError

from src.core.events.domain import START, EventStreamUnavailable, StreamEvent

# Enough history for a client to reconnect after a dropped connection without a gap; old
# entries are trimmed, and an idle stream expires so finished conversations cost nothing.
MAX_LENGTH = 1000
TTL_SECONDS = 60 * 60

# redis-py gives every connection a 5-second read timeout by default, which cuts off any
# XREAD that blocks longer -- a quiet stream would die at 5s instead of keeping alive at 15.
# Reads may block up to this long; it stays finite so a dead connection is still noticed.
READ_TIMEOUT_SECONDS = 60
CONNECT_TIMEOUT_SECONDS = 5
MAX_BLOCK_MILLISECONDS = (READ_TIMEOUT_SECONDS - 10) * 1000


class RedisEventStream:
    """EventStream on Redis Streams: XADD to publish, XREAD BLOCK to wait for the next event."""

    def __init__(self, connection_url: str, prefix: str = "events") -> None:
        self._redis = redis.from_url(
            connection_url,
            decode_responses=True,
            socket_timeout=READ_TIMEOUT_SECONDS,
            socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
            health_check_interval=30,
        )
        self._prefix = prefix

    def _key(self, topic: str) -> str:
        return f"{self._prefix}:{topic}"

    async def publish(self, topic: str, type: str, data: dict[str, Any]) -> str:
        key = self._key(topic)
        try:
            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.xadd(key, {"type": type, "data": json.dumps(data, default=str)}, maxlen=MAX_LENGTH, approximate=True)
                pipe.expire(key, TTL_SECONDS)
                event_id, _ = await pipe.execute()
        except RedisError as exc:
            raise EventStreamUnavailable(f"could not publish to {topic}: {exc}") from exc
        return str(event_id)

    async def last_id(self, topic: str) -> str:
        try:
            newest = await self._redis.xrevrange(self._key(topic), count=1)
        except RedisError as exc:
            raise EventStreamUnavailable(f"could not read {topic}: {exc}") from exc
        return str(newest[0][0]) if newest else START

    async def read(self, topic: str, after: str, block_milliseconds: int) -> list[StreamEvent]:
        block = min(block_milliseconds, MAX_BLOCK_MILLISECONDS)
        try:
            # [(key, [(id, {field: value}), ...])] -- redis-py types it loosely
            found: Any = await self._redis.xread({self._key(topic): after}, block=block, count=100)
        except RedisError as exc:
            raise EventStreamUnavailable(f"could not read {topic}: {exc}") from exc

        events = []
        for _, entries in found or []:
            for event_id, fields in entries:
                events.append(
                    StreamEvent(id=str(event_id), type=fields["type"], data=json.loads(fields["data"]))
                )
        return events

    async def aclose(self) -> None:
        await self._redis.aclose()
