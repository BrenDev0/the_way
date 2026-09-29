from uuid import uuid4

import pytest
from helpers import FakeLLM, make_completion

from src.conversations import events as conversation_events
from src.conversations import tasks as conversation_tasks
from src.conversations import use_cases as conversations_use_cases
from src.conversations.domain import ConversationCreate
from src.conversations.sqlalchemy import adapter as conversations_adapter
from src.core.events.domain import EventStreamUnavailable
from src.core.events.memory import InMemoryEventStream
from src.core.events.redis.adapter import RedisEventStream
from src.core.llm.domain import ToolCall
from src.core.settings import settings
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter


async def test_redis_streams_keep_events_for_a_reader_that_arrives_late():
    stream = RedisEventStream(settings.REDIS_URL, prefix=f"test-{uuid4().hex[:8]}")
    try:
        assert await stream.last_id("t") == "0-0"
        first = await stream.publish("t", "status", {"status": "running"})
        await stream.publish("t", "text", {"text": "hi"})

        late = await stream.read("t", "0-0", 10)
        resumed = await stream.read("t", first, 10)

        assert [(e.type, e.data) for e in late] == [("status", {"status": "running"}), ("text", {"text": "hi"})]
        assert [e.type for e in resumed] == ["text"]
        assert await stream.read("t", await stream.last_id("t"), 50) == []
    finally:
        await stream.aclose()


async def test_a_read_may_block_past_the_redis_client_default_timeout():
    # redis-py cuts a connection's reads off at 5s unless told otherwise; the keep-alive is 15s
    stream = RedisEventStream(settings.REDIS_URL, prefix=f"test-{uuid4().hex[:8]}")
    try:
        assert await stream.read("t", "0-0", 6000) == []
    finally:
        await stream.aclose()


async def test_an_unreachable_redis_is_reported_as_unavailable():
    stream = RedisEventStream("redis://127.0.0.1:1/0")
    try:
        with pytest.raises(EventStreamUnavailable):
            await stream.read("t", "0-0", 10)
    finally:
        await stream.aclose()


async def test_the_pause_is_published_only_after_it_is_committed(db_session):
    organization = await organizations_adapter.create(db_session, OrganizationCreate(name="Acme"))
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
    conversation = await conversations_adapter.create(
        db_session, ConversationCreate(organization_id=organization.id, user_id=user.id, title="Desk")
    )
    await db_session.commit()

    async def get(cid, uid):
        return await conversations_adapter.get_for_user(db_session, cid, uid)

    async def append(cid, msgs):
        return await conversations_adapter.append_messages(db_session, cid, msgs)

    async def save(cid, turn):
        return await conversations_adapter.save_turn_state(db_session, cid, turn)

    await conversations_use_cases.send_message(conversation.id, user.id, "read notes.txt", get, append, save)
    await db_session.commit()

    stream = InMemoryEventStream()
    read = ToolCall(id="read-1", name="ReadFile", args={"file_path": "notes.txt"})
    await conversation_tasks.run_turn(conversation.id, llm=FakeLLM(make_completion("", (read,))), event_stream=stream)

    events = stream.of(conversation_events.topic(conversation.id))
    status = events[-1]
    assert status.type == "status"
    assert status.data["status"] == "awaiting_client"
    assert status.data["pendingToolCalls"][0]["name"] == "ReadFile"
    assert status.data["pendingToolCalls"][0]["location"] == "desktop"

    # by the time anyone hears of it, the database already agrees
    await db_session.rollback()
    stored = await conversations_adapter.get_by_id(db_session, conversation.id)
    assert stored.turn.status.value == "awaiting_client"
