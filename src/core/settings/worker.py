from .base import AppSettings


class WorkerSettings(AppSettings):
    """What only the worker's queue consumer reads. The api builds the same broker to send
    tasks but never consumes, so none of these matters there; set them on the worker."""

    # How long XREADGROUP waits on Redis for a message, and how long a read on that socket
    # may take. The read must outlast the wait by a wide margin: redis-py's default (5s)
    # left 3s, and one stretch of synchronous work in a task was enough to time the read
    # out -- which kills the worker process and the turn it was running.
    TASKIQ_XREAD_BLOCK_MS: int = 2000
    TASKIQ_SOCKET_TIMEOUT_SECONDS: float = 60
    # A message unacknowledged this long is taken back and run again: how a turn whose
    # worker died is recovered. A live worker renews every message it holds each
    # TASKIQ_HEARTBEAT_SECONDS (core/tasks/broker.py), so a turn that is merely long is
    # never run twice. Renewal stops after TASKIQ_HEARTBEAT_MAX_SECONDS, for a message that
    # is never acknowledged (one taskiq could not parse or route).
    TASKIQ_IDLE_TIMEOUT_SECONDS: int = 300
    TASKIQ_HEARTBEAT_SECONDS: int = 60
    TASKIQ_HEARTBEAT_MAX_SECONDS: int = 6 * 60 * 60


settings = WorkerSettings()
