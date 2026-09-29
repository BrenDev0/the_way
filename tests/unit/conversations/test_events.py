import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

from helpers import FakeLLM, make_completion
from pydantic import BaseModel

from src.conversations import events as conversation_events
from src.conversations import use_cases
from src.conversations.domain import Conversation, ConversationStatus, TurnState
from src.core.events import sse
from src.core.events.domain import EventStreamUnavailable
from src.core.events.memory import InMemoryEventStream
from src.core.llm import domain as llm_domain
from src.core.llm.domain import ToolCall
from src.core.tools.domain import Tool
from src.core.tools.executor import Executor
from src.core.tools.gates import SuspendGate


class ListProjects(BaseModel):
    pass


async def list_projects() -> str:
    return "Website"


def conversation(status=ConversationStatus.RUNNING) -> Conversation:
    now = datetime.now(UTC)
    return Conversation(
        id=uuid4(), organization_id=uuid4(), user_id=uuid4(), title="Thread",
        turn=TurnState(status=status), created_at=now, updated_at=now,
    )


class Store:
    def __init__(self, current: Conversation):
        self.current = current
        self.messages = [llm_domain.user("hi")]

    async def get(self, _id):
        return self.current

    async def list_messages(self, _id):
        return list(self.messages)

    async def append(self, _id, messages):
        self.messages.extend(messages)
        return len(messages)

    async def save(self, _id, turn):
        self.current.turn = turn
        return self.current


async def test_a_turn_streams_its_text_messages_and_tool_activity():
    stream = InMemoryEventStream()
    store = Store(conversation())
    events = conversation_events.ConversationEvents(stream, store.current.id)
    llm = FakeLLM(
        make_completion("", (ToolCall(id="c1", name="ListProjects", args={}),)),
        "You have one project.",
    )

    await use_cases.advance_turn(
        store.current.id,
        llm,
        Executor({"ListProjects": Tool(schema=ListProjects, handler=list_projects)}, SuspendGate(), events),
        store.get,
        store.list_messages,
        store.append,
        store.save,
        observer=events,
    )

    published = stream.of(conversation_events.topic(store.current.id))
    types = [event.type for event in published]
    assert types[:4] == ["message", "tool.started", "tool.finished", "message"]
    assert published[0].data["toolCalls"] == [{"id": "c1", "name": "ListProjects", "args": {}}]
    assert published[3].data == {"role": "tool", "content": "Website", "toolCallId": "c1"}
    text = "".join(event.data["text"] for event in published if event.type == "text")
    assert text == "You have one project."
    assert types[-1] == "message"


async def test_a_long_tool_result_is_clipped_on_the_stream():
    stream = InMemoryEventStream()
    events = conversation_events.ConversationEvents(stream, uuid4())

    await events.on_message(llm_domain.tool_result("c1", "x" * 10_000))

    (event,) = next(iter(stream.events.values()))
    assert len(event.data["content"]) <= conversation_events.PREVIEW_CHARS + 1


async def test_status_carries_the_pending_calls_in_the_api_shape():
    stream = InMemoryEventStream()
    current = conversation(ConversationStatus.AWAITING_CLIENT)

    await conversation_events.ConversationEvents(stream, current.id).status(current)

    (event,) = stream.of(conversation_events.topic(current.id))
    assert event.type == "status"
    assert event.data["status"] == "awaiting_client"
    assert event.data["pendingToolCalls"] == []
    assert event.data["id"] == str(current.id)


async def collect(generator, count: int, timeout: float = 2.0) -> list[str]:
    frames: list[str] = []

    async def take():
        async for frame in generator:
            frames.append(frame)
            if len(frames) == count:
                return

    await asyncio.wait_for(take(), timeout)
    return frames


async def test_a_watcher_gets_the_snapshot_then_live_events_with_resumable_ids():
    stream = InMemoryEventStream()
    conversation_id = uuid4()
    topic = conversation_events.topic(conversation_id)
    await stream.publish(topic, "text", {"text": "old"})
    after = await stream.last_id(topic)

    async def never():
        return False

    watcher = conversation_events.follow(stream, conversation_id, after, {"status": "running"}, never, 5, 60)
    await stream.publish(topic, "text", {"text": "new"})
    frames = await collect(watcher, 2)

    assert frames[0] == 'event: status\ndata: {"status":"running"}\n\n'
    assert frames[1].startswith("id: 2-0\nevent: text\n")
    assert json.loads(frames[1].split("data: ")[1]) == {"text": "new"}


async def test_a_quiet_stream_sends_keep_alives():
    stream = InMemoryEventStream()

    async def never():
        return False

    watcher = conversation_events.follow(stream, uuid4(), "0-0", {}, never, 0.05, 60)
    frames = await collect(watcher, 3)

    assert frames[1:] == [sse.KEEP_ALIVE, sse.KEEP_ALIVE]


async def test_a_watcher_stops_when_the_client_leaves():
    stream = InMemoryEventStream()
    gone = False

    async def disconnected():
        return gone

    watcher = conversation_events.follow(stream, uuid4(), "0-0", {}, disconnected, 0.05, 60)
    first = await collect(watcher, 1)
    gone = True

    remaining = [frame async for frame in watcher]
    assert first and remaining == []


def test_only_a_real_stream_id_is_resumed_from():
    assert conversation_events.resume_point("1727650000000-3") == "1727650000000-3"
    assert conversation_events.resume_point("$") is None
    assert conversation_events.resume_point("0; DROP") is None
    assert conversation_events.resume_point(None) is None


async def test_a_stream_ends_after_its_lifetime_so_the_client_reconnects():
    stream = InMemoryEventStream()

    async def never():
        return False

    watcher = conversation_events.follow(stream, uuid4(), "0-0", {}, never, 0.05, 0.2)
    frames = await asyncio.wait_for(_all(watcher), 2)

    assert frames[0].startswith("event: status")
    assert all(frame == sse.KEEP_ALIVE for frame in frames[1:])


async def test_an_assistant_inside_a_tool_publishes_its_calls_under_that_tool():
    stream = InMemoryEventStream()
    events = conversation_events.ConversationEvents(stream, uuid4())
    inner = Executor({"ListProjects": Tool(schema=ListProjects, handler=list_projects)}, SuspendGate(), events)

    class BuildPage(BaseModel):
        pass

    async def build_page() -> str:
        # what a page builder does: its own assistant, calling tools of its own
        await inner.execute([ToolCall(id="inner-1", name="ListProjects", args={})])
        return "built"

    outer = Executor({"BuildPage": Tool(schema=BuildPage, handler=build_page)}, SuspendGate(), events)
    await outer.execute([ToolCall(id="outer-1", name="BuildPage", args={})])

    published = [(e.type, e.data["id"], e.data.get("parentId")) for e in next(iter(stream.events.values()))]
    assert published == [
        ("tool.started", "outer-1", None),
        ("tool.started", "inner-1", "outer-1"),
        ("tool.finished", "inner-1", "outer-1"),
        ("tool.finished", "outer-1", None),
    ]


class DownStream(InMemoryEventStream):
    async def publish(self, topic, type, data):
        raise EventStreamUnavailable("redis is down")

    async def read(self, topic, after, block_milliseconds):
        raise EventStreamUnavailable("redis is down")


async def test_a_stream_whose_store_fails_ends_instead_of_crashing():
    async def never():
        return False

    watcher = conversation_events.follow(DownStream(), uuid4(), "0-0", {"status": "running"}, never, 5, 60)
    frames = await asyncio.wait_for(_all(watcher), 2)

    assert frames == ['event: status\ndata: {"status":"running"}\n\n']


async def test_publishing_to_a_store_that_fails_does_not_fail_the_turn():
    events = conversation_events.ConversationEvents(DownStream(), uuid4())

    await events.on_text("hi")
    await events.status(conversation())


async def _all(generator) -> list[str]:
    return [frame async for frame in generator]
