from dataclasses import dataclass
from typing import Any

# The id to read after when a stream has no history yet.
START = "0-0"


class EventStreamUnavailable(Exception):
    """The stream's backing store could not be reached. Nothing is lost -- published
    events are kept -- so a reader stops and its client reconnects to carry on."""


@dataclass(frozen=True)
class StreamEvent:
    """One entry of a stream: its id (which a client echoes back as Last-Event-ID to resume
    after it), a type, and a JSON-serialisable payload."""

    id: str
    type: str
    data: dict[str, Any]
