from datetime import UTC, datetime
from uuid import uuid4

import pytest
from helpers import FakeLLM, make_completion
from pydantic import BaseModel

from src.conversations import use_cases
from src.conversations.domain import (
    Conversation,
    ConversationStatus,
    PauseReason,
    TurnPause,
    TurnState,
)
from src.core.exceptions import ConflictError
from src.core.llm import domain as llm_domain
from src.core.llm.domain import LLMUnavailable, TokenUsage, ToolCall, UnavailableReason
from src.core.tools.domain import Tool
from src.core.tools.executor import Executor
from src.core.tools.gates import DenyGate


class Search(BaseModel):
    query: str


async def search(query: str) -> str:
    return f"results for {query}"


def make_conversation(turn: TurnState) -> Conversation:
    now = datetime.now(UTC)
    return Conversation(
        id=uuid4(), organization_id=uuid4(), user_id=uuid4(), title="Thread",
        turn=turn, created_at=now, updated_at=now,
    )


class Store:
    def __init__(self, conversation, history=()):
        self.conversation = conversation
        self.messages = list(history)
        self.saved: list[TurnState] = []
        self.commits = 0
        # the messages stored at each commit
        self.committed: list[list] = []

    async def get_for_user(self, conversation_id, user_id):
        return self.conversation if self.conversation.user_id == user_id else None

    async def get_by_id(self, conversation_id):
        return self.conversation

    async def list_messages(self, conversation_id):
        return list(self.messages)

    async def append(self, conversation_id, messages):
        self.messages.extend(messages)
        return len(messages)

    async def save(self, conversation_id, turn):
        self.saved.append(turn)
        self.conversation.turn = turn
        return self.conversation

    async def commit(self):
        self.commits += 1
        self.committed.append(list(self.messages))


def rate_limited():
    return LLMUnavailable(UnavailableReason.RATE_LIMIT, "429 slow down", retry_after=30)


def searching(call_id):
    return make_completion("", (ToolCall(id=call_id, name="Search", args={"query": call_id}),))


async def advance(store, llm):
    return await use_cases.advance_turn(
        store.conversation.id,
        llm,
        Executor({"Search": Tool(schema=Search, handler=search)}, DenyGate()),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
        commit_fn=store.commit,
    )


def running(**changes):
    return make_conversation(TurnState(status=ConversationStatus.RUNNING, **changes))


async def test_an_unreachable_model_pauses_the_turn_with_why():
    store = Store(running(), history=[llm_domain.user("research this")])

    status = await advance(store, FakeLLM(rate_limited()))

    assert status is ConversationStatus.PAUSED
    pause = store.saved[-1].pause
    assert pause.reason is PauseReason.RATE_LIMIT
    assert pause.detail == "429 slow down"
    assert (pause.retry_after - pause.paused_at).total_seconds() == pytest.approx(30)


async def test_the_work_before_the_pause_is_kept():
    store = Store(running(), history=[llm_domain.user("research this")])
    llm = FakeLLM(searching("a"), searching("b"), rate_limited())

    await advance(store, llm)

    roles = [m["role"] for m in store.messages]
    assert roles == ["user", "assistant", "tool", "assistant", "tool"]
    assert store.messages[-1]["content"] == "results for b"
    assert store.saved[-1].iterations_used == 2


async def test_each_step_is_committed_before_the_next_model_call():
    store = Store(running(), history=[llm_domain.user("research this")])

    await advance(store, FakeLLM(searching("a"), searching("b"), "done"))

    # after each round of tool results, before the model saw them
    assert store.commits == 2
    assert [m["role"] for m in store.committed[0]] == ["user", "assistant", "tool"]
    assert all(turn.status is ConversationStatus.RUNNING for turn in store.saved[:-1])


async def test_a_turn_with_nothing_new_is_not_checkpointed():
    store = Store(running(), history=[llm_domain.user("hi")])

    await advance(store, FakeLLM("hello"))

    assert store.commits == 0


async def test_resuming_carries_on_after_the_last_tool_result():
    store = Store(running(), history=[llm_domain.user("research this")])
    await advance(store, FakeLLM(searching("a"), rate_limited()))

    await use_cases.resume_turn(
        store.conversation.id, store.conversation.user_id, store.get_for_user, store.save
    )
    llm = FakeLLM("here is what I found")
    status = await advance(store, llm)

    assert status is ConversationStatus.IDLE
    # the model is sent everything done before the pause, ending on the search result
    assert llm.received[0][-1] == {"role": "tool", "content": "results for a", "tool_call_id": "a"}
    assert [m["role"] for m in store.messages] == ["user", "assistant", "tool", "assistant"]


async def test_resuming_clears_the_pause_and_keeps_the_count():
    turn = TurnState(
        status=ConversationStatus.PAUSED,
        iterations_used=3,
        usage=TokenUsage(10, 5, 15),
        pause=TurnPause(PauseReason.QUOTA),
    )
    store = Store(make_conversation(turn))

    await use_cases.resume_turn(
        store.conversation.id, store.conversation.user_id, store.get_for_user, store.save
    )

    resumed = store.saved[-1]
    assert resumed.status is ConversationStatus.RUNNING
    assert resumed.pause is None
    assert resumed.iterations_used == 3
    assert resumed.usage.total_tokens == 15


@pytest.mark.parametrize(
    "status", [ConversationStatus.IDLE, ConversationStatus.RUNNING, ConversationStatus.FAILED]
)
async def test_only_a_paused_turn_can_be_resumed(status):
    store = Store(make_conversation(TurnState(status=status)))

    with pytest.raises(ConflictError) as exc:
        await use_cases.resume_turn(
            store.conversation.id, store.conversation.user_id, store.get_for_user, store.save
        )

    assert exc.value.code == "conversation_not_paused"


async def test_a_new_message_may_follow_a_paused_turn():
    store = Store(make_conversation(TurnState(status=ConversationStatus.PAUSED, pause=TurnPause(PauseReason.TIMEOUT))))

    await use_cases.send_message(
        store.conversation.id, store.conversation.user_id, "never mind, try this",
        store.get_for_user, store.append, store.save,
    )

    assert store.saved[-1].status is ConversationStatus.RUNNING
    assert store.saved[-1].pause is None


def test_a_pause_with_nothing_said_is_shown_through_the_api():
    from src.conversations import mapper

    conversation = make_conversation(
        TurnState(status=ConversationStatus.PAUSED, pause=TurnPause(PauseReason.INTERRUPTED))
    )

    response = mapper.domain_to_conversation_response(conversation)

    assert response.pause.reason is PauseReason.INTERRUPTED
    assert response.pause.detail == ""
