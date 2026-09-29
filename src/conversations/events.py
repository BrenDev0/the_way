"""What a conversation tells whoever is watching it, as it happens.

Every event lands on the conversation's stream; GET /conversations/{id}/events relays
them as server-sent events. The types:

  status        the conversation as the API returns it -- sent whenever the turn's state
                is saved: running, awaiting_client (with the calls it waits on), idle, failed
  text          a piece of the assistant's reply, as the model writes it
  message       a message the turn added: the assistant's (with any tool calls) or a tool
                result, clipped -- the full thread is always at GET .../messages
  tool.started  a server-side tool began running
  tool.finished it ended, and whether it failed
"""

import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import UUID

from src.core.events import sse
from src.core.events.domain import EventStreamUnavailable
from src.core.events.ports import EventStream
from src.core.llm.domain import Message, ToolCall
from src.core.tools.domain import ToolResult

from . import mapper
from .domain import Conversation

# A tool result can be a whole file or dataset; the stream carries enough to show progress.
PREVIEW_CHARS = 2000


EVENT_ID = re.compile(r"^\d+-\d+$")


def topic(conversation_id: UUID) -> str:
    return f"conversation:{conversation_id}"


def resume_point(last_event_id: str | None) -> str | None:
    """The Last-Event-ID a reconnecting client sent, if it is a real stream id."""
    return last_event_id if last_event_id and EVENT_ID.match(last_event_id) else None


async def follow(
    stream: EventStream,
    conversation_id: UUID,
    after: str,
    snapshot: dict[str, Any],
    disconnected: Callable[[], Awaitable[bool]],
    keep_alive_seconds: float,
    max_seconds: float,
) -> AsyncIterator[str]:
    """The server-sent events for one watcher.

    It opens with the conversation's current state, so a client never has to guess where
    things stand, then relays everything published after `after` -- which the caller takes
    before reading that state, so nothing can fall between the two. A quiet stretch sends a
    keep-alive instead, which also notices a client that has gone away.

    After max_seconds it ends, and the client reconnects with Last-Event-ID and loses
    nothing. That bounds a stream whose client vanished without the server being told --
    behind some proxies a disconnect is never reported.
    """
    deadline = time.monotonic() + max_seconds
    # no id: the snapshot is not a stream entry, and must not move the client's resume point
    yield sse.frame("status", snapshot)
    while time.monotonic() < deadline and not await disconnected():
        try:
            events = await stream.read(topic(conversation_id), after, int(keep_alive_seconds * 1000))
        except EventStreamUnavailable:
            # end the stream rather than crash it: the client reconnects from `after`
            return
        if not events:
            yield sse.KEEP_ALIVE
            continue
        for event in events:
            after = event.id
            yield sse.frame(event.type, event.data, event.id)


class ConversationEvents:
    def __init__(self, stream: EventStream, conversation_id: UUID) -> None:
        self._stream = stream
        self._topic = topic(conversation_id)

    async def _publish(self, type: str, data: dict[str, Any]) -> None:
        # Telling watchers is best-effort: the turn's state is in the database either way,
        # and a watcher that reconnects is handed it. A turn must never fail over this.
        try:
            await self._stream.publish(self._topic, type, data)
        except EventStreamUnavailable:
            return

    async def status(self, conversation: Conversation) -> None:
        body = mapper.domain_to_conversation_response(conversation).model_dump(mode="json", by_alias=True)
        await self._publish("status", body)

    # --- LoopObserver ---------------------------------------------------------------

    async def on_text(self, text: str) -> None:
        await self._publish("text", {"text": text})

    async def on_message(self, message: Message) -> None:
        content = message.get("content", "")
        if isinstance(content, str) and len(content) > PREVIEW_CHARS:
            content = content[:PREVIEW_CHARS] + "…"
        body: dict[str, Any] = {"role": message["role"], "content": content}
        if message.get("tool_calls"):
            body["toolCalls"] = [
                {"id": call["id"], "name": call["name"], "args": call["args"]} for call in message["tool_calls"]
            ]
        if message.get("tool_call_id"):
            body["toolCallId"] = message["tool_call_id"]
        await self._publish("message", body)

    # --- ToolEvents -----------------------------------------------------------------

    async def tool_started(self, call: ToolCall) -> None:
        await self._publish("tool.started", {"id": call.id, "name": call.name, "args": call.args})

    async def tool_finished(self, call: ToolCall, result: ToolResult) -> None:
        await self._publish("tool.finished", {"id": call.id, "name": call.name, "failed": result.failed})
