from taskiq import AsyncBroker, InMemoryBroker
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from src.core.settings import settings


def build_broker() -> AsyncBroker:
    if settings.TASKIQ_BROKER_URL == "memory://":
        return InMemoryBroker()

    result_backend: RedisAsyncResultBackend = RedisAsyncResultBackend(
        redis_url=settings.taskiq_result_backend_url(),
        result_ex_time=settings.TASKIQ_RESULT_TTL_SECONDS,
    )
    return RedisStreamBroker(
        url=settings.TASKIQ_BROKER_URL,
        stream_name=settings.TASKIQ_STREAM_NAME,
        consumer_group_name=settings.TASKIQ_CONSUMER_GROUP,
    ).with_result_backend(result_backend)


broker: AsyncBroker = build_broker()
