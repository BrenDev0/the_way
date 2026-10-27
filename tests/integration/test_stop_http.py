"""The Stop and Continue endpoints over HTTP, on the real app: what the desktop app calls.

Kept apart from the async tests: the app runs on the test client's event loop."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.background.domain import BackgroundTaskCreate, TaskStatus
from src.background.sqlalchemy import adapter as background_adapter
from src.conversations.domain import (
    ConversationCreate,
    ConversationStatus,
    PauseReason,
    TurnState,
)
from src.conversations.sqlalchemy import adapter as conversations_adapter
from src.core import stop as stop_signal
from src.core.database.sqlalchemy.core import async_session_factory
from src.core.llm import domain as llm_domain
from src.core.llm.domain import ToolCall
from src.fastapi.main import app
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

PASSWORD = "Sup3rSecret!pass"
API = "/api/desktop/v1"


@pytest.fixture(scope="module")
def client():
    from src.core.database.sqlalchemy.core import engine

    with TestClient(app) as test_client:
        yield test_client
        test_client.portal.call(engine.dispose)


@pytest.fixture(autouse=True)
def dispose_shared_engine():
    yield


def sign_up(client):
    """An organization with a user (an owner key is not needed: Stop never calls a model)."""
    email = f"stop-{uuid4().hex[:10]}@example.com"
    hashing, encryption = app.state.hashing_service, app.state.encryption_service
    found: dict = {}

    async def seed():
        async with async_session_factory() as session:
            organization = await organizations_adapter.create(session, OrganizationCreate(name="Stop Co"))
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
            found.update(organization=organization.id, user=user.id, conversation=conversation.id)

    client.portal.call(seed)
    token = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD, "deviceName": "Stop"}).json()["token"]
    found["headers"] = {"Authorization": f"Bearer {token}"}
    return found


@pytest.fixture
def person(client):
    return sign_up(client)


def set_turn(client, conversation_id, turn, messages=()):
    async def run():
        async with async_session_factory() as session:
            if messages:
                await conversations_adapter.append_messages(session, conversation_id, list(messages))
            await conversations_adapter.save_turn_state(session, conversation_id, turn)
            await session.commit()

    client.portal.call(run)


def read_turn(client, conversation_id):
    async def run():
        async with async_session_factory() as session:
            return (
                await conversations_adapter.get_by_id(session, conversation_id),
                await conversations_adapter.list_messages(session, conversation_id),
            )

    return client.portal.call(run)


def flag(client, key):
    async def run():
        return await stop_signal.requested(app.state.cache_store, key)

    return client.portal.call(run)


def test_stopping_a_working_turn_is_accepted_and_raises_the_flag(client, person):
    set_turn(client, person["conversation"], TurnState(status=ConversationStatus.RUNNING))

    response = client.post(f"{API}/conversations/{person['conversation']}/stop", headers=person["headers"])

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "running"  # the worker ends it a moment later
    assert flag(client, stop_signal.conversation_key(person["conversation"])) is True


def test_stopping_a_turn_that_waits_on_the_desktop_ends_it_and_answers_its_calls(client, person):
    calls = (ToolCall(id="c1", name="ReadFile", args={"file_path": "a.txt"}),)
    set_turn(
        client,
        person["conversation"],
        TurnState(status=ConversationStatus.AWAITING_CLIENT, pending_tool_calls=calls),
        messages=[llm_domain.user("read it"), llm_domain.assistant("", calls)],
    )

    response = client.post(f"{API}/conversations/{person['conversation']}/stop", headers=person["headers"])

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "paused"
    assert body["pause"]["reason"] == PauseReason.STOPPED.value
    _, messages = read_turn(client, person["conversation"])
    assert [m["role"] for m in messages[-3:]] == ["assistant", "tool", "system"]


def test_there_is_nothing_to_stop_in_an_idle_conversation(client, person):
    response = client.post(f"{API}/conversations/{person['conversation']}/stop", headers=person["headers"])

    assert response.status_code == 409
    assert response.json()["code"] == "conversation_not_running"


def test_nobody_can_stop_someone_elses_conversation(client, person):
    other = sign_up(client)

    response = client.post(f"{API}/conversations/{person['conversation']}/stop", headers=other["headers"])

    assert response.status_code == 404


def test_stopping_needs_a_signed_in_user(client, person):
    assert client.post(f"{API}/conversations/{person['conversation']}/stop").status_code == 401


def test_continuing_a_stopped_turn_runs_it_again_and_tells_the_agent(client, person, monkeypatch):
    from src.conversations.domain import TurnPause
    from src.conversations.fastapi.routes import turns as turn_routes

    sent = []

    async def kiq(conversation_id, **kwargs):
        sent.append(conversation_id)

    monkeypatch.setattr(turn_routes.advance_conversation, "kiq", kiq)
    set_turn(
        client,
        person["conversation"],
        TurnState(status=ConversationStatus.PAUSED, pause=TurnPause(reason=PauseReason.STOPPED)),
    )

    response = client.post(f"{API}/conversations/{person['conversation']}/resume", json={}, headers=person["headers"])

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "running"
    assert sent == [person["conversation"]]
    _, messages = read_turn(client, person["conversation"])
    assert messages[-1]["role"] == "system" and "pressed Continue" in messages[-1]["content"]


# --- background tasks -------------------------------------------------------------------------------


def make_task(client, person, status=TaskStatus.RUNNING):
    async def run():
        async with async_session_factory() as session:
            task = await background_adapter.create(
                session,
                BackgroundTaskCreate(
                    organization_id=person["organization"],
                    user_id=person["user"],
                    conversation_id=person["conversation"],
                    description="Audit",
                    instructions="Audit it",
                ),
            )
            await background_adapter.set_status(session, task.id, status)
            await session.commit()
            return task.id

    return client.portal.call(run)


def test_stopping_a_running_task_is_accepted_and_raises_its_flag(client, person):
    task_id = make_task(client, person)

    response = client.post(f"{API}/background-tasks/{task_id}/stop", headers=person["headers"])

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "running"
    assert flag(client, stop_signal.task_key(task_id)) is True


def test_stopping_a_task_that_is_not_running_is_refused(client, person):
    task_id = make_task(client, person, TaskStatus.DONE)

    response = client.post(f"{API}/background-tasks/{task_id}/stop", headers=person["headers"])

    assert response.status_code == 409
    assert response.json()["code"] == "task_not_running"


def test_resuming_a_stopped_task_runs_it_again(client, person, monkeypatch):
    from src.background import jobs

    sent = []

    async def kiq(task_id):
        sent.append(task_id)

    monkeypatch.setattr(jobs.run_background_task, "kiq", kiq)
    task_id = make_task(client, person, TaskStatus.STOPPED)

    response = client.post(f"{API}/background-tasks/{task_id}/resume", headers=person["headers"])

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "running"
    assert sent == [task_id]


def test_resuming_a_task_that_is_not_stopped_is_refused(client, person):
    task_id = make_task(client, person, TaskStatus.RUNNING)

    response = client.post(f"{API}/background-tasks/{task_id}/resume", headers=person["headers"])

    assert response.status_code == 409
    assert response.json()["code"] == "task_not_stopped"


def test_nobody_can_stop_or_resume_someone_elses_task(client, person):
    other = sign_up(client)
    task_id = make_task(client, person, TaskStatus.STOPPED)

    assert client.post(f"{API}/background-tasks/{task_id}/stop", headers=other["headers"]).status_code == 404
    assert client.post(f"{API}/background-tasks/{task_id}/resume", headers=other["headers"]).status_code == 404
