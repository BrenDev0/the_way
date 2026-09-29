"""Server-sent events framing (text/event-stream)."""

import json
from typing import Any

# A comment line: ignored by every SSE client, but enough traffic to keep proxies and
# load balancers from closing a connection that has been quiet for a while.
KEEP_ALIVE = ": keep-alive\n\n"

HEADERS = {
    "Cache-Control": "no-cache",
    # tells nginx-style proxies not to buffer the stream, which would hold events back
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


def frame(type: str, data: dict[str, Any], event_id: str | None = None) -> str:
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {type}")
    # JSON has no raw newlines, so the payload is always a single data line
    lines.append(f"data: {json.dumps(data, default=str, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"
