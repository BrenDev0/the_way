from typing import Any, Protocol

from .domain import StreamEvent


class EventStream(Protocol):
    """Append-only event streams, one per topic, that readers can resume.

    Unlike plain publish/subscribe, an event published while nobody is listening is kept
    (for a while), so a client that reconnects asks for everything after the last id it
    saw and misses nothing -- which matters when the event is "the turn is waiting on you".
    """

    async def publish(self, topic: str, type: str, data: dict[str, Any]) -> str: ...

    async def last_id(self, topic: str) -> str:
        """The id of the newest event, or START when there is none."""
        ...

    async def read(self, topic: str, after: str, block_milliseconds: int) -> list[StreamEvent]:
        """Events after `after`, waiting up to the block time for the first one. An empty
        list means nothing happened in that time."""
        ...

    async def aclose(self) -> None: ...
