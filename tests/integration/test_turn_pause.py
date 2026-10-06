import asyncio
from uuid import uuid4

import pytest
from helpers import FakeLLM, make_completion

from src.conversations import tasks as conversation_tasks
from src.conversations import use_cases as conversations_use_cases
from src.conversations.domain import ConversationCreate, ConversationStatus, PauseReason
from src.conversations.sqlalchemy import adapter as conversations_adapter
from src.core.llm.domain import LLMUnavailable, ToolCall, UnavailableReason
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter


@pytest.fixture
async def conversation(db_session):
    organization = await organizations_adapter.create(db_session, OrganizationCreate(name="Acme Inc"))
    user = await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=organization.id,
            encrypted_email=f"enc::{uuid4()}@example.com",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::secret",
            role=Role.OWNER,
        ),
    )
    created = await conversations_adapter.create(
        db_session,
        ConversationCreate(organization_id=organization.id, user_id=user.id, title="First thread"),
    )
    await db_session.commit()
    return created


def store_fns(db_session):
    return {
        "get_conversation_for_user_fn": lambda cid, uid: conversations_adapter.get_for_user(db_session, cid, uid),
        "save_turn_state_fn": lambda cid, turn: conversations_adapter.save_turn_state(db_session, cid, turn),
    }


async def send(db_session, conversation, message):
    await conversations_use_cases.send_message(
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        message=message,
        append_messages_fn=lambda cid, msgs: conversations_adapter.append_messages(db_session, cid, msgs),
        **store_fns(db_session),
    )
    await db_session.commit()


async def reload(db_session, conversation):
    await db_session.rollback()
    return await conversations_adapter.get_by_id(db_session, conversation.id)


# A tool every conversation has, with no key: reading the user's memory/preferences is
# not needed -- an unknown tool name is enough to make a tool result.
def calling_a_tool():
    return make_completion("", (ToolCall(id="c1", name="NoSuchTool", args={}),))


async def test_a_rate_limit_pauses_the_turn_and_keeps_its_work(db_session, conversation):
    await send(db_session, conversation, "research this")
    llm = FakeLLM(calling_a_tool(), LLMUnavailable(UnavailableReason.RATE_LIMIT, "429", retry_after=20))

    status = await conversation_tasks.run_turn(conversation.id, llm=llm, run="message-1")

    current = await reload(db_session, conversation)
    assert status is ConversationStatus.PAUSED
    assert current.turn.status is ConversationStatus.PAUSED
    assert current.turn.pause.reason is PauseReason.RATE_LIMIT
    assert current.turn.pause.retry_after is not None
    messages = await conversations_adapter.list_messages(db_session, conversation.id)
    assert [m["role"] for m in messages if m["role"] != "system"] == ["user", "assistant", "tool"]


async def test_a_resumed_turn_carries_on_and_finishes(db_session, conversation):
    await send(db_session, conversation, "research this")
    await conversation_tasks.run_turn(
        conversation.id, llm=FakeLLM(calling_a_tool(), LLMUnavailable(UnavailableReason.TIMEOUT)), run="m1"
    )
    current = await reload(db_session, conversation)
    current.user_id = conversation.user_id

    await conversations_use_cases.resume_turn(conversation.id, conversation.user_id, **store_fns(db_session))
    await db_session.commit()
    llm = FakeLLM("here it is")
    status = await conversation_tasks.run_turn(conversation.id, llm=llm, run="m2")

    current = await reload(db_session, conversation)
    assert status is ConversationStatus.IDLE
    assert current.turn.pause is None
    assert llm.received[0][-1]["role"] == "tool"
    messages = await conversations_adapter.list_messages(db_session, conversation.id)
    assert [m["role"] for m in messages if m["role"] != "system"] == ["user", "assistant", "tool", "assistant"]


class Hangs:
    """A model call the worker is cancelled in the middle of -- it shutting down."""

    def __init__(self, first):
        self.first = first
        self.started = asyncio.Event()

    async def respond(self, messages, tools=(), on_text=None):
        if self.first is not None:
            reply, self.first = self.first, None
            return reply
        self.started.set()
        await asyncio.sleep(3600)


async def test_a_turn_cut_off_by_the_worker_going_down_is_paused_with_its_work(db_session, conversation):
    await send(db_session, conversation, "research this")
    llm = Hangs(calling_a_tool())

    running = asyncio.create_task(conversation_tasks.run_turn(conversation.id, llm=llm, run="m1"))
    await llm.started.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    current = await reload(db_session, conversation)
    assert current.turn.status is ConversationStatus.PAUSED
    assert current.turn.pause.reason is PauseReason.INTERRUPTED
    # the tool ran before the cut, and its checkpoint was committed
    messages = await conversations_adapter.list_messages(db_session, conversation.id)
    assert [m["role"] for m in messages if m["role"] != "system"] == ["user", "assistant", "tool"]


async def test_a_second_message_for_a_claimed_turn_does_not_run_it(db_session, conversation):
    await send(db_session, conversation, "hello")
    assert await conversations_adapter.claim_turn(db_session, conversation.id, "first")
    await db_session.commit()

    llm = FakeLLM()  # called at all, it fails the test
    original = conversation_tasks.READY_ATTEMPTS
    conversation_tasks.READY_ATTEMPTS = 2
    try:
        status = await conversation_tasks.run_turn(conversation.id, llm=llm, run="second")
    finally:
        conversation_tasks.READY_ATTEMPTS = original

    assert status is None
    assert llm.received == []


async def test_the_message_holding_the_turn_may_take_it_again(db_session, conversation):
    await send(db_session, conversation, "hello")
    assert await conversations_adapter.claim_turn(db_session, conversation.id, "first")
    await db_session.commit()

    status = await conversation_tasks.run_turn(conversation.id, llm=FakeLLM("hi"), run="first")

    assert status is ConversationStatus.IDLE
