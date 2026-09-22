from datetime import UTC, datetime
from typing import Annotated

from taskiq import TaskiqDepends

from src.core.cache.ports import CacheStore
from src.core.tasks.broker import broker

from . import dependencies as worker_dependencies

PROBE_KEY = "tasks:health:probe"


@broker.task
async def ping() -> str:
    return datetime.now(UTC).isoformat()


@broker.task
async def check_dependencies(
    cache_store: Annotated[CacheStore, TaskiqDepends(worker_dependencies.get_cache_store)],
) -> bool:
    stamp = datetime.now(UTC).isoformat()
    await cache_store.store_str(PROBE_KEY, stamp, 60)
    return await cache_store.get_str(PROBE_KEY) == stamp
