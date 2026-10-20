"""The organization tab's two routes end to end: the real app, Postgres and Redis, over HTTP,
signed and signed in as the panel does -- so the routes' wiring across slices is exercised,
not only the use cases behind them."""

import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.core.database.sqlalchemy.core import async_session_factory
from src.fastapi import signing
from src.fastapi.main import app
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

PASSWORD = "Sup3rSecret!pass"
WEB = "/api/v1"


@pytest.fixture(scope="module")
def client():
    from src.core.database.sqlalchemy.core import engine

    with TestClient(app) as test_client:
        yield test_client
        test_client.portal.call(engine.dispose)


@pytest.fixture(autouse=True)
def dispose_shared_engine():
    """Replaces the package-wide fixture: the app here runs on the test client's loop."""
    yield


def signed(method, path, body=b""):
    timestamp = str(int(time.time()))
    return {
        signing.SIGNATURE_HEADER: signing.build_signature(method, path, timestamp, body),
        signing.TIMESTAMP_HEADER: timestamp,
    }


@pytest.fixture
def organization(client):
    """An organization with an owner and a plain member, each able to sign in."""
    hashing = app.state.hashing_service
    encryption = app.state.encryption_service
    people = {}

    async def seed():
        async with async_session_factory() as session:
            created = await organizations_adapter.create(session, OrganizationCreate(name="Overview Co"))
            for role in (Role.OWNER, Role.MEMBER):
                address = f"{role.value}-{uuid4().hex[:8]}@example.com"
                await users_adapter.create(
                    session,
                    UserCreate(
                        organization_id=created.id,
                        encrypted_email=encryption.encrypt(address),
                        email_hash=hashing.deterministic_hash(address),
                        password_hash=hashing.hash_password(PASSWORD),
                        role=role,
                    ),
                )
                people[role] = address
            await session.commit()

    client.portal.call(seed)
    return people


def sign_in(client, address):
    client.cookies.clear()
    body = json.dumps({"email": address, "password": PASSWORD}).encode()
    response = client.post(
        f"{WEB}/auth/login",
        content=body,
        headers={**signed("POST", f"{WEB}/auth/login", body), "Content-Type": "application/json"},
    )
    assert response.status_code == 200, response.text
    return response.json()["user"]["id"]


def test_an_owner_reads_the_overview(client, organization):
    owner_id = sign_in(client, organization[Role.OWNER])

    path = f"{WEB}/organizations/me/overview"
    response = client.get(path, headers=signed("GET", path))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["seats"] == {"limit": None, "members": 2, "pending": 0}
    assert body["ownerId"] == owner_id
    assert body["storage"] == {"bytes": 0, "files": 0, "library": None, "byPerson": [], "largest": []}
    assert body["orphans"] == []


def test_an_owner_reads_the_usage_for_the_months_asked(client, organization):
    sign_in(client, organization[Role.OWNER])

    path = f"{WEB}/organizations/me/usage?months=3"
    response = client.get(path, headers=signed("GET", path))

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["months"]) == 3
    assert all(month.endswith("-01") for month in body["months"])
    assert body["rows"] == []


def test_a_plain_member_cannot_read_either(client, organization):
    sign_in(client, organization[Role.MEMBER])

    for path in (f"{WEB}/organizations/me/overview", f"{WEB}/organizations/me/usage"):
        response = client.get(path, headers=signed("GET", path))

        assert response.status_code == 403, path
        assert response.json()["code"] == "insufficient_role"


def test_the_usage_window_is_capped(client, organization):
    sign_in(client, organization[Role.OWNER])

    path = f"{WEB}/organizations/me/usage?months=99"
    response = client.get(path, headers=signed("GET", path))

    assert response.status_code == 422
