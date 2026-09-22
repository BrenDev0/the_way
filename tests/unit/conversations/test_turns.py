from datetime import UTC, datetime
from uuid import uuid4

import pytest
from helpers import FakeLLM, make_completion

from src.conversations import use_cases
from src.conversations.domain import Conversation, ConversationStatus, TurnState
from src.core.exceptions import ConflictError, NotFoundError
from src.core.llm import domain as llm_domain
from src.core.llm.domain import TokenUsage, ToolCall
from src.core.tools.domain import Tool
from src.core.tools.executor import Executor
from src.core.tools.gates import DenyGate


def make_conversation(status=ConversationStatus.IDLE, turn=None, user_id=None):
    now = datetime.now(UTC)
    return Conversation(
        id=uuid4(),
        organization_id=uuid4(),
        user_id=user_id or uuid4(),
        title="Thread",
        turn=turn or TurnState(status=status),
        created_at=now,
        updated_at=now,
    )


class Store:
    def __init__(self, conversation, history=()):
        self.conversation = conversation
        self.messages = list(history)
        self.saved: list[TurnState] = []

    async def get_for_user(self, conversation_id, user_id):
        if self.conversation.user_id != user_id:
            return None
        return self.conversation

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


def executor():
    return Executor({}, DenyGate())


async def test_sending_a_message_stores_it():
    store = Store(make_conversation())

    await use_cases.send_message(
        store.conversation.id,
        store.conversation.user_id,
        "hello",
        store.get_for_user,
        store.append,
        store.save,
    )

    assert store.messages == [{"role": "user", "content": "hello"}]


async def test_sending_a_message_marks_the_conversation_running():
    store = Store(make_conversation())

    await use_cases.send_message(
        store.conversation.id,
        store.conversation.user_id,
        "hello",
        store.get_for_user,
        store.append,
        store.save,
    )

    assert store.saved[0].status is ConversationStatus.RUNNING


async def test_cumulative_usage_survives_a_new_turn():
    store = Store(make_conversation(turn=TurnState(usage=TokenUsage(10, 5, 15))))

    await use_cases.send_message(
        store.conversation.id,
        store.conversation.user_id,
        "hello",
        store.get_for_user,
        store.append,
        store.save,
    )

    assert store.saved[0].usage.total_tokens == 15
    assert store.saved[0].iterations_used == 0


async def test_sending_to_someone_elses_conversation_is_not_found():
    store = Store(make_conversation())

    with pytest.raises(NotFoundError):
        await use_cases.send_message(
            store.conversation.id, uuid4(), "hello", store.get_for_user, store.append, store.save
        )

    assert store.messages == []


@pytest.mark.parametrize(
    "status", [ConversationStatus.RUNNING, ConversationStatus.AWAITING_APPROVAL]
)
async def test_sending_while_busy_is_rejected(status):
    store = Store(make_conversation(status=status))

    with pytest.raises(ConflictError) as exc:
        await use_cases.send_message(
            store.conversation.id,
            store.conversation.user_id,
            "hello",
            store.get_for_user,
            store.append,
            store.save,
        )

    assert exc.value.code == "conversation_busy"
    assert store.messages == []


async def test_advancing_appends_only_the_new_messages():
    store = Store(
        make_conversation(status=ConversationStatus.RUNNING),
        history=[llm_domain.user("hello")],
    )
    llm = FakeLLM("hi there")

    await use_cases.advance_turn(
        store.conversation.id,
        llm,
        executor(),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
    )

    assert [m["content"] for m in store.messages] == ["hello", "hi there"]


async def test_the_system_prompt_is_never_persisted():
    store = Store(
        make_conversation(status=ConversationStatus.RUNNING),
        history=[llm_domain.user("hello")],
    )

    await use_cases.advance_turn(
        store.conversation.id,
        FakeLLM("hi"),
        executor(),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
    )

    assert all(m["role"] != "system" for m in store.messages)


async def test_the_system_prompt_is_sent_to_the_model():
    store = Store(
        make_conversation(status=ConversationStatus.RUNNING),
        history=[llm_domain.user("hello")],
    )
    llm = FakeLLM("hi")

    await use_cases.advance_turn(
        store.conversation.id,
        llm,
        executor(),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
    )

    assert llm.received[0][0]["role"] == "system"


async def test_a_finished_turn_goes_back_to_idle():
    store = Store(make_conversation(status=ConversationStatus.RUNNING))

    status = await use_cases.advance_turn(
        store.conversation.id,
        FakeLLM("done"),
        executor(),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
    )

    assert status is ConversationStatus.IDLE
    assert store.saved[-1].status is ConversationStatus.IDLE


async def test_running_out_of_iterations_marks_it_failed():
    call = ToolCall(id="c1", name="Nope", args={})
    store = Store(make_conversation(status=ConversationStatus.RUNNING))
    llm = FakeLLM(*[make_completion("", (call,)) for _ in range(3)])

    status = await use_cases.advance_turn(
        store.conversation.id,
        llm,
        executor(),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
        max_iterations=2,
    )

    assert status is ConversationStatus.FAILED


async def test_usage_accumulates_onto_the_conversation():
    store = Store(make_conversation(turn=TurnState(status=ConversationStatus.RUNNING,
                                                   usage=TokenUsage(10, 5, 15))))
    llm = FakeLLM(make_completion("done", usage=TokenUsage(20, 10, 30)))

    await use_cases.advance_turn(
        store.conversation.id,
        llm,
        executor(),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
    )

    assert store.saved[-1].usage.total_tokens == 45


async def test_a_conversation_that_is_not_running_is_left_alone():
    store = Store(make_conversation(status=ConversationStatus.IDLE))
    llm = FakeLLM("should not be called")

    status = await use_cases.advance_turn(
        store.conversation.id,
        llm,
        executor(),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
    )

    assert status is None
    assert llm.received == []


async def test_a_missing_conversation_is_left_alone():
    async def missing(conversation_id):
        return None

    store = Store(make_conversation())
    llm = FakeLLM("should not be called")

    status = await use_cases.advance_turn(
        uuid4(), llm, executor(), missing, store.list_messages, store.append, store.save
    )

    assert status is None
    assert llm.received == []


async def test_a_gated_tool_leaves_the_conversation_awaiting_approval():
    from pydantic import BaseModel

    class DeleteFile(BaseModel):
        path: str

    async def delete_file(path: str) -> str:
        return "deleted"

    class Suspending:
        async def decide(self, requests):
            from src.core.tools.domain import ApprovalRequired

            raise ApprovalRequired(tuple(requests))

    tools = {"DeleteFile": Tool(schema=DeleteFile, handler=delete_file, requires_approval=True)}
    store = Store(make_conversation(status=ConversationStatus.RUNNING))
    call = ToolCall(id="c1", name="DeleteFile", args={"path": "x"})

    status = await use_cases.advance_turn(
        store.conversation.id,
        FakeLLM(make_completion("", (call,))),
        Executor(tools, Suspending()),
        store.get_by_id,
        store.list_messages,
        store.append,
        store.save,
    )

    assert status is ConversationStatus.AWAITING_APPROVAL
    assert store.saved[-1].pending_tool_calls[0].id == "c1"
