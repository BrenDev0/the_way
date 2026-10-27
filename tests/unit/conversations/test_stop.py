"""The user pressing Stop on a conversation, and Continue after it."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from helpers import FakeLLM, make_completion
from pydantic import BaseModel

from src.conversations import prompt
from src.conversations.domain import (
    Conversation,
    ConversationClient,
    ConversationStatus,
    PauseReason,
    TurnPause,
    TurnState,
)
from src.conversations.use_cases import advance as advance_use_cases
from src.conversations.use_cases import turns as turn_use_cases
from src.core.agents.loop import NOT_RUN
from src.core.exceptions import ConflictError, NotFoundError
from src.core.llm import domain as llm_domain
from src.core.llm.domain import ToolCall
from src.core.tools.domain import Tool
from src.core.tools.executor import Executor
from src.core.tools.gates import DenyGate


def conversation(turn: TurnState) -> Conversation:
    now = datetime.now(UTC)
    return Conversation(
        id=uuid4(),
        organization_id=uuid4(),
        user_id=uuid4(),
        title="t",
        client=ConversationClient.DESKTOP,
        turn=turn,
        created_at=now,
        updated_at=now,
    )


class Store:
    """A conversation held in memory, with the ports the use cases take."""

    def __init__(self, current: Conversation | None) -> None:
        self.current = current
        self.appended: list = []
        self.stops: int = 0

    async def get(self, conversation_id, user_id):
        return self.current

    async def append(self, conversation_id, messages):
        self.appended.extend(messages)

    async def save(self, conversation_id, turn):
        self.current.turn = turn
        return self.current

    async def request_stop(self):
        self.stops += 1


async def stop(store):
    return await turn_use_cases.stop_turn(
        uuid4(),
        uuid4(),
        get_conversation_for_user_fn=store.get,
        append_messages_fn=store.append,
        save_turn_state_fn=store.save,
        request_stop_fn=store.request_stop,
    )


async def test_stopping_a_working_turn_asks_the_worker_and_changes_nothing_itself():
    store = Store(conversation(TurnState(status=ConversationStatus.RUNNING)))

    result = await stop(store)

    assert store.stops == 1
    assert result.turn.status is ConversationStatus.RUNNING
    assert store.appended == []


async def test_stopping_a_turn_waiting_on_the_client_ends_it_now_with_every_call_answered():
    calls = (ToolCall(id="c1", name="ReadFile", args={}), ToolCall(id="c2", name="DeleteFile", args={}))
    store = Store(
        conversation(TurnState(status=ConversationStatus.AWAITING_CLIENT, pending_tool_calls=calls, iterations_used=3))
    )

    result = await stop(store)

    assert result.turn.status is ConversationStatus.PAUSED
    assert result.turn.pause.reason is PauseReason.STOPPED
    assert result.turn.pending_tool_calls == ()
    assert result.turn.iterations_used == 3
    assert store.stops == 0
    roles = [(m["role"], m.get("tool_call_id")) for m in store.appended]
    assert roles == [("tool", "c1"), ("tool", "c2"), ("system", None)]
    assert all(NOT_RUN in m["content"] for m in store.appended[:2])
    assert store.appended[-1]["content"] == prompt.STOPPED_NOTE


@pytest.mark.parametrize("status", [ConversationStatus.IDLE, ConversationStatus.PAUSED, ConversationStatus.FAILED])
async def test_there_is_nothing_to_stop_when_nothing_runs(status):
    store = Store(conversation(TurnState(status=status)))

    with pytest.raises(ConflictError) as exc:
        await stop(store)

    assert exc.value.code == "conversation_not_running"


async def test_another_users_conversation_is_not_found():
    with pytest.raises(NotFoundError):
        await stop(Store(None))


async def test_continuing_a_stopped_turn_tells_the_agent_so():
    store = Store(
        conversation(TurnState(status=ConversationStatus.PAUSED, pause=TurnPause(reason=PauseReason.STOPPED)))
    )

    result = await turn_use_cases.resume_turn(
        uuid4(), uuid4(), store.get, store.save, append_messages_fn=store.append
    )

    assert result.turn.status is ConversationStatus.RUNNING
    assert store.appended == [llm_domain.system(prompt.RESUMED_NOTE)]


async def test_continuing_after_a_rate_limit_adds_no_note():
    store = Store(
        conversation(TurnState(status=ConversationStatus.PAUSED, pause=TurnPause(reason=PauseReason.RATE_LIMIT)))
    )

    await turn_use_cases.resume_turn(uuid4(), uuid4(), store.get, store.save, append_messages_fn=store.append)

    assert store.appended == []


class ReadFile(BaseModel):
    path: str


async def read_file(path: str) -> str:
    return "contents"


async def test_a_turn_stopped_in_the_loop_is_paused_as_stopped_and_the_agent_is_told():
    """advance_turn ends a stopped loop as PAUSED/STOPPED, keeps what was done and writes the note."""
    stored = []
    current = conversation(TurnState(status=ConversationStatus.RUNNING))
    stopped = {"yes": False}

    async def get(_id):
        return current

    async def list_messages(_id):
        return [llm_domain.user("do it")]

    async def append(_id, messages):
        stored.extend(messages)

    async def save(_id, turn):
        current.turn = turn
        return current

    async def should_stop():
        # the first look (before the model's first reply) lets it work; later ones stop it
        if stopped["yes"]:
            return True
        stopped["yes"] = True
        return False

    llm = FakeLLM(make_completion("", (ToolCall(id="c1", name="ReadFile", args={"path": "a"}),)), "never")

    status = await advance_use_cases.advance_turn(
        conversation_id=current.id,
        llm=llm,
        executor=Executor({"ReadFile": Tool(schema=ReadFile, handler=read_file)}, DenyGate()),
        get_conversation_by_id_fn=get,
        list_messages_fn=list_messages,
        append_messages_fn=append,
        save_turn_state_fn=save,
        should_stop=should_stop,
    )

    assert status is ConversationStatus.PAUSED
    assert current.turn.pause.reason is PauseReason.STOPPED
    assert [m["role"] for m in stored] == ["assistant", "tool", "system"]
    assert stored[-1]["content"] == prompt.STOPPED_NOTE
    assert len(llm.received) == 1
