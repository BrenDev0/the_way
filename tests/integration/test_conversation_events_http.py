"""The events endpoint over HTTP, against the real app. Kept apart from the async tests:
the app runs on the test client's event loop, so this module skips the shared engine cleanup."""

import asyncio
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.conversations import config as conversations_config
from src.conversations import events as conversation_events
from src.conversations.domain import ConversationCreate
from src.conversations.sqlalchemy import adapter as conversations_adapter
from src.core.database.sqlalchemy.core import async_session_factory
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

PASSWORD = "Sup3rSecret!pass"


@pytest.fixture(scope="module")
def client():
    from src.core.database.sqlalchemy.core import engine

    with TestClient(app) as test_client:
        yield test_client
        test_client.portal.call(engine.dispose)


@pytest.fixture(autouse=True)
def dispose_shared_engine():
    """The app runs on the test client's loop; see test_desktop_auth."""
    yield


@pytest.fixture
def signed_in(client):
    email = f"sse-{uuid4().hex[:10]}@example.com"
    hashing = app.state.hashing_service
    encryption = app.state.encryption_service

    async def seed():
        async with async_session_factory() as session:
            organization = await organizations_adapter.create(session, OrganizationCreate(name="SSE Co"))
            user = await users_adapter.create(
                session,
                UserCreate(
                    organization_id=organization.id,
                    encrypted_email=encryption.encrypt(email),
                    email_hash=hashing.deterministic_hash(email),
                    password_hash=hashing.hash_password(PASSWORD),
                    role=Role.OWNER,
                ),
            )
            conversation = await conversations_adapter.create(
                session, ConversationCreate(organization_id=organization.id, user_id=user.id, title="Live")
            )
            await session.commit()
            return conversation.id

    conversation_id = client.portal.call(seed)
    token = client.post(
        "/api/desktop/v1/auth/login", json={"email": email, "password": PASSWORD, "deviceName": "SSE"}
    ).json()["token"]
    return conversation_id, {"Authorization": f"Bearer {token}"}


def read_frames(response, count: int, timeout: float = 5.0) -> list[str]:
    frames, buffer, deadline = [], "", time.monotonic() + timeout
    for chunk in response.iter_text():
        buffer += chunk
        while "\n\n" in buffer:
            frame, buffer = buffer.split("\n\n", 1)
            frames.append(frame)
        if len(frames) >= count or time.monotonic() > deadline:
            break
    return frames


def test_the_stream_opens_with_the_state_then_relays_and_keeps_alive(client, signed_in, monkeypatch):
    conversation_id, headers = signed_in
    monkeypatch.setattr(conversations_config, "KEEP_ALIVE_SECONDS", 0.3)
    # the test client never reports a disconnect, so the stream has to end on its own
    monkeypatch.setattr(conversations_config, "STREAM_MAX_SECONDS", 1.5)

    async def publish_mid_stream():
        # the test client reads a streamed body to its end before returning it, so the event
        # is published from the app's own loop while the stream is still open
        await asyncio.sleep(0.5)
        await app.state.event_stream.publish(
            conversation_events.topic(conversation_id), "text", {"text": "streamed"}
        )

    client.portal.start_task_soon(publish_mid_stream)
    with client.stream("GET", f"/api/desktop/v1/conversations/{conversation_id}/events", headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = read_frames(response, 10)

    # the snapshot always comes first; the event and the keep-alives follow in any order
    assert frames[0].startswith("event: status")
    assert '"status":"idle"' in frames[0]
    assert any(f.startswith("id: ") and '"text":"streamed"' in f for f in frames[1:])
    assert ": keep-alive" in frames[1:]


def test_someone_elses_conversation_cannot_be_watched(client, signed_in):
    _, headers = signed_in

    response = client.get(f"/api/desktop/v1/conversations/{uuid4()}/events", headers=headers)

    assert response.status_code == 404


def test_the_stream_needs_the_token(client, signed_in):
    conversation_id, _ = signed_in

    response = client.get(f"/api/desktop/v1/conversations/{conversation_id}/events")

    assert response.status_code == 401
