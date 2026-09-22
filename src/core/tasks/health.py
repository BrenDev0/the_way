from datetime import UTC, datetime
from typing import Annotated

from taskiq import TaskiqDepends

from src.api import dependencies as api_dependencies
from src.core.cache.ports import CacheStore

from .broker import broker

PROBE_KEY = "tasks:health:probe"


@broker.task
async def ping() -> str:
    return datetime.now(UTC).isoformat()


@broker.task
async def check_dependencies(
    cache_store: Annotated[CacheStore, TaskiqDepends(api_dependencies.get_cache_store)],
) -> bool:
    stamp = datetime.now(UTC).isoformat()
    await cache_store.store_str(PROBE_KEY, stamp, 60)
    return await cache_store.get_str(PROBE_KEY) == stamp
