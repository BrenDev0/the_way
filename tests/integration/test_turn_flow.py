from uuid import uuid4

import pytest
from helpers import make_completion

from src.conversations import tasks as conversation_tasks
from src.conversations import use_cases as conversations_use_cases
from src.conversations.domain import ConversationCreate, ConversationStatus
from src.conversations.sqlalchemy import adapter as conversations_adapter
from src.core.llm.domain import Completion, Message
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter


class ScriptedLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def respond(self, messages: list[Message]) -> Completion:
        return make_completion(self.reply)


@pytest.fixture
async def conversation(db_session):
    organization = await organizations_adapter.create(
        db_session, OrganizationCreate(name="Acme Inc")
    )
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
        ConversationCreate(
            organization_id=organization.id, user_id=user.id, title="First thread"
        ),
    )
    await db_session.commit()
    return created


@pytest.fixture
def scripted_llm():
    return ScriptedLLM("the assistant reply")


async def send_and_run(db_session, conversation, message: str, llm):
    await conversations_use_cases.send_message(
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        message=message,
        get_conversation_for_user_fn=lambda cid, uid: conversations_adapter.get_for_user(
            db_session, cid, uid
        ),
        append_messages_fn=lambda cid, msgs: conversations_adapter.append_messages(
            db_session, cid, msgs
        ),
        save_turn_state_fn=lambda cid, turn: conversations_adapter.save_turn_state(
            db_session, cid, turn
        ),
    )
    await db_session.commit()

    await conversation_tasks.run_turn(conversation.id, llm)

    await db_session.rollback()
    current = await conversations_adapter.get_by_id(db_session, conversation.id)
    assert current is not None
    return current


async def test_a_message_runs_a_full_turn(db_session, conversation, scripted_llm):
    finished = await send_and_run(db_session, conversation, "hello there", scripted_llm)

    assert finished.turn.status is ConversationStatus.IDLE


async def test_the_reply_is_persisted(db_session, conversation, scripted_llm):
    await send_and_run(db_session, conversation, "hello there", scripted_llm)

    await db_session.rollback()
    messages = await conversations_adapter.list_messages(db_session, conversation.id)

    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "hello there"
    assert messages[1]["content"] == "the assistant reply"


async def test_the_system_prompt_is_not_persisted(db_session, conversation, scripted_llm):
    await send_and_run(db_session, conversation, "hello there", scripted_llm)

    await db_session.rollback()
    messages = await conversations_adapter.list_messages(db_session, conversation.id)

    assert all(m["role"] != "system" for m in messages)


async def test_a_second_turn_keeps_the_history(db_session, conversation, scripted_llm):
    await send_and_run(db_session, conversation, "first question", scripted_llm)
    await db_session.rollback()
    refreshed = await conversations_adapter.get_by_id(db_session, conversation.id)
    refreshed.user_id = conversation.user_id

    await send_and_run(db_session, refreshed, "second question", scripted_llm)

    await db_session.rollback()
    messages = await conversations_adapter.list_messages(db_session, conversation.id)

    assert [m["content"] for m in messages] == [
        "first question",
        "the assistant reply",
        "second question",
        "the assistant reply",
    ]


async def test_iterations_reset_between_turns(db_session, conversation, scripted_llm):
    first = await send_and_run(db_session, conversation, "first", scripted_llm)

    assert first.turn.iterations_used == 1
