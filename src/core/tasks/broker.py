import asyncio
import logging
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from taskiq import AsyncBroker, InMemoryBroker
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from src.core.settings import settings

logger = logging.getLogger(__name__)


class HeartbeatStreamBroker(RedisStreamBroker):
    """A Redis stream broker that keeps hold of every message its worker is running.

    The stream takes back a message left unacknowledged for idle_timeout and runs it
    again -- the recovery for a worker that died mid-turn. But a message is acknowledged
    only when its task finishes, so a turn or background task that simply ran longer
    than the timeout was started a second time beside the first: two copies of one turn
    calling the model, running tools and writing the conversation. Here the worker
    renews its claim on each message it holds (XCLAIM ... JUSTID, which resets the idle
    clock and keeps the owner) until the message is acknowledged. A dead worker renews
    nothing, so its messages still come back after idle_timeout.
    """

    def __init__(self, *args, heartbeat: float, heartbeat_max: float, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.heartbeat = heartbeat
        self.heartbeat_max = heartbeat_max
        # held so the loop does not garbage-collect a running heartbeat
        self._beats: set[asyncio.Task[None]] = set()

    def _ack_generator(self, id: str, queue_name: str) -> Callable[[], Awaitable[None]]:
        # Called as listen() hands the message to the worker -- the moment it is held.
        ack = super()._ack_generator(id, queue_name)
        beat = asyncio.create_task(self._keep_claimed(id, queue_name))
        self._beats.add(beat)
        beat.add_done_callback(self._beats.discard)

        async def _ack() -> None:
            beat.cancel()
            await ack()

        return _ack

    async def _keep_claimed(self, id: str, queue_name: str) -> None:
        loop = asyncio.get_running_loop()
        stop = loop.time() + self.heartbeat_max
        while loop.time() < stop:
            await asyncio.sleep(self.heartbeat)
            try:
                # a connection per renewal, not one held for the whole task: fifty running
                # tasks would otherwise sit on fifty connections of the pool
                async with Redis(connection_pool=self.connection_pool) as redis:
                    await redis.xclaim(
                        queue_name,
                        self.consumer_group_name,
                        self.consumer_name,
                        min_idle_time=0,
                        message_ids=[id],
                        justid=True,
                    )
            except Exception:  # a missed beat is retried; the task runs on
                logger.warning("could not renew the claim on message %s", id, exc_info=True)

    async def shutdown(self) -> None:
        for beat in list(self._beats):
            beat.cancel()
        await super().shutdown()


def build_broker() -> AsyncBroker:
    if settings.TASKIQ_BROKER_URL == "memory://":
        return InMemoryBroker()

    result_backend: RedisAsyncResultBackend = RedisAsyncResultBackend(
        redis_url=settings.taskiq_result_backend_url(),
        result_ex_time=settings.TASKIQ_RESULT_TTL_SECONDS,
    )
    return HeartbeatStreamBroker(
        url=settings.TASKIQ_BROKER_URL,
        queue_name=settings.TASKIQ_STREAM_NAME,
        consumer_group_name=settings.TASKIQ_CONSUMER_GROUP,
        # where a new consumer group starts reading: the beginning, so nothing queued
        # before the group existed is skipped (each worker's own name is a random uuid)
        consumer_id="0",
        xread_block=settings.TASKIQ_XREAD_BLOCK_MS,
        # One message per read. A batch is handed out as slots free up, and the ones still
        # waiting in it are neither running nor renewed: they went idle and were taken back
        # and run twice, and with several workers one of them hoarded the queue.
        xread_count=1,
        idle_timeout=settings.TASKIQ_IDLE_TIMEOUT_SECONDS * 1000,
        heartbeat=settings.TASKIQ_HEARTBEAT_SECONDS,
        heartbeat_max=settings.TASKIQ_HEARTBEAT_MAX_SECONDS,
        socket_timeout=settings.TASKIQ_SOCKET_TIMEOUT_SECONDS,
    ).with_result_backend(result_backend)


broker: AsyncBroker = build_broker()
