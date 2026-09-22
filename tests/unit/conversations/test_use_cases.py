from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.conversations import use_cases
from src.conversations.domain import Conversation, ConversationCreate, TurnState
from src.core.exceptions import NotFoundError
from src.core.llm import domain as llm_domain


def make_conversation(user_id=None, organization_id=None, title="Thread"):
    now = datetime.now(UTC)
    return Conversation(
        id=uuid4(),
        organization_id=organization_id or uuid4(),
        user_id=user_id or uuid4(),
        title=title,
        turn=TurnState(),
        created_at=now,
        updated_at=now,
    )


def scoped_getter(conversation):
    """Mirrors the adapter: a row is returned only when the user owns it."""

    async def get_conversation_for_user_fn(conversation_id, user_id):
        if conversation is None or conversation.user_id != user_id:
            return None
        return conversation

    return get_conversation_for_user_fn


async def test_starting_a_conversation_binds_it_to_the_caller():
    created = []

    async def create_fn(conversation: ConversationCreate):
        created.append(conversation)
        return make_conversation(conversation.user_id, conversation.organization_id)

    user_id, organization_id = uuid4(), uuid4()

    await use_cases.start_conversation(organization_id, user_id, "Thread", create_fn)

    assert created[0].user_id == user_id
    assert created[0].organization_id == organization_id


async def test_reading_your_own_conversation():
    conversation = make_conversation()

    found = await use_cases.get_conversation(
        conversation.id, conversation.user_id, scoped_getter(conversation)
    )

    assert found.id == conversation.id


async def test_the_user_id_reaches_the_query():
    seen = []

    async def get_fn(conversation_id, user_id):
        seen.append((conversation_id, user_id))

    conversation_id, user_id = uuid4(), uuid4()

    with pytest.raises(NotFoundError):
        await use_cases.get_conversation(conversation_id, user_id, get_fn)

    assert seen == [(conversation_id, user_id)]


async def test_another_users_conversation_is_not_found():
    conversation = make_conversation()

    with pytest.raises(NotFoundError) as exc:
        await use_cases.get_conversation(conversation.id, uuid4(), scoped_getter(conversation))

    assert exc.value.code == "conversation_not_found"


async def test_a_foreign_conversation_is_indistinguishable_from_a_missing_one():
    conversation = make_conversation()

    with pytest.raises(NotFoundError) as foreign:
        await use_cases.get_conversation(conversation.id, uuid4(), scoped_getter(conversation))
    with pytest.raises(NotFoundError) as missing:
        await use_cases.get_conversation(uuid4(), uuid4(), scoped_getter(None))

    assert foreign.value.code == missing.value.code
    assert foreign.value.message == missing.value.message


async def test_reading_messages_you_own():
    async def list_fn(conversation_id, user_id):
        return [llm_domain.user("hi")]

    messages = await use_cases.read_messages(uuid4(), uuid4(), list_fn)

    assert messages[0]["content"] == "hi"


async def test_messages_for_a_conversation_you_do_not_own_are_not_found():
    async def list_fn(conversation_id, user_id):
        return None

    with pytest.raises(NotFoundError) as exc:
        await use_cases.read_messages(uuid4(), uuid4(), list_fn)

    assert exc.value.code == "conversation_not_found"


async def test_an_empty_thread_is_not_mistaken_for_a_missing_one():
    async def list_fn(conversation_id, user_id):
        return []

    assert await use_cases.read_messages(uuid4(), uuid4(), list_fn) == []


async def test_deleting_your_own_conversation():
    async def delete_fn(conversation_id, user_id):
        return True

    await use_cases.delete_conversation(uuid4(), uuid4(), delete_fn)


async def test_deleting_someone_elses_conversation_is_not_found():
    async def delete_fn(conversation_id, user_id):
        return False

    with pytest.raises(NotFoundError) as exc:
        await use_cases.delete_conversation(uuid4(), uuid4(), delete_fn)

    assert exc.value.code == "conversation_not_found"


async def test_delete_passes_both_ids_to_the_query():
    seen = []

    async def delete_fn(conversation_id, user_id):
        seen.append((conversation_id, user_id))
        return True

    conversation_id, user_id = uuid4(), uuid4()
    await use_cases.delete_conversation(conversation_id, user_id, delete_fn)

    assert seen == [(conversation_id, user_id)]


async def test_listing_only_asks_for_the_callers_conversations():
    seen = []

    async def list_fn(user_id):
        seen.append(user_id)
        return []

    user_id = uuid4()
    await use_cases.list_conversations(user_id, list_fn)

    assert seen == [user_id]
