import asyncio
from typing import Any

from .domain import START, StreamEvent


class InMemoryEventStream:
    """EventStream held in the process, for tests and for runs with nothing listening."""

    def __init__(self) -> None:
        self.events: dict[str, list[StreamEvent]] = {}
        self._counter = 0
        self._changed = asyncio.Condition()

    async def publish(self, topic: str, type: str, data: dict[str, Any]) -> str:
        async with self._changed:
            self._counter += 1
            event = StreamEvent(id=f"{self._counter}-0", type=type, data=data)
            self.events.setdefault(topic, []).append(event)
            self._changed.notify_all()
        return event.id

    async def last_id(self, topic: str) -> str:
        events = self.events.get(topic)
        return events[-1].id if events else START

    async def read(self, topic: str, after: str, block_milliseconds: int) -> list[StreamEvent]:
        def newer() -> list[StreamEvent]:
            position = _sequence(after)
            return [e for e in self.events.get(topic, []) if _sequence(e.id) > position]

        async with self._changed:
            if not newer() and block_milliseconds > 0:
                try:
                    await asyncio.wait_for(self._changed.wait_for(lambda: bool(newer())), block_milliseconds / 1000)
                except TimeoutError:
                    return []
            return newer()

    def of(self, topic: str) -> list[StreamEvent]:
        return list(self.events.get(topic, []))

    async def aclose(self) -> None:
        return None


def _sequence(event_id: str) -> int:
    return int(event_id.split("-")[0])
