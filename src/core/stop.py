"""The user's request to stop work that is under way.

A stop is a flag kept for a short while, because the worker doing the work is another process:
the API sets it, and the worker looks at it at the points where it can stop cleanly (between
steps, and while a reply is being written). It is a request, not a command -- nothing is
interrupted half-way -- and it expires on its own, so one that was never read cannot stop
the next piece of work.
"""

from uuid import UUID

from src.core.cache.ports import CacheStore

# Long enough for a worker to be reached and a long step to end; short enough that a flag
# nobody read is gone before anyone could mistake it for a new request.
EXPIRE_SECONDS = 600


def conversation_key(conversation_id: UUID) -> str:
    return f"stop:conversation:{conversation_id}"


def task_key(task_id: UUID) -> str:
    return f"stop:task:{task_id}"


async def request(cache: CacheStore, key: str) -> None:
    await cache.store_bool(key, True, EXPIRE_SECONDS)


async def requested(cache: CacheStore, key: str) -> bool:
    return bool(await cache.get_bool(key))


async def clear(cache: CacheStore, key: str) -> None:
    await cache.remove(key)
