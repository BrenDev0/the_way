"""Provider keys set by staff for an organization, end to end: the real app and Postgres, over
HTTP, signed and signed in as the dashboard and the customer panel are.

What matters: the key reaches every user of that organization and nobody else, the secret goes
in once and never comes back, and customers have no route of their own for keys any more."""

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
from src.staff.domain import StaffMemberCreate
from src.staff.sqlalchemy import adapter as staff_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

PASSWORD = "Sup3rSecret!pass"
WEB = "/api/v1"
SECRET = "sk-ant-api03-REALLY-SECRET-9876"


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


def call(client, method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else b""
    timestamp = str(int(time.time()))
    headers = {
        signing.SIGNATURE_HEADER: signing.build_signature(method, path, timestamp, body),
        signing.TIMESTAMP_HEADER: timestamp,
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    return client.request(method, path, content=body or None, headers=headers)


@pytest.fixture
def staff(client):
    address = f"staff-{uuid4().hex[:8]}@xplorers.example"
    hashing, encryption = app.state.hashing_service, app.state.encryption_service

    async def seed():
        async with async_session_factory() as session:
            await staff_adapter.create_member(
                session,
                StaffMemberCreate(
                    encrypted_email=encryption.encrypt(address),
                    email_hash=hashing.deterministic_hash(address),
                    password_hash=hashing.hash_password(PASSWORD),
                ),
            )
            await session.commit()

    client.portal.call(seed)
    client.cookies.clear()
    assert call(client, "POST", f"{WEB}/staff/auth/login", {"email": address, "password": PASSWORD}).status_code == 200
    return address


def make_organization(client, member_roles=(Role.OWNER, Role.MEMBER)):
    """An organization with one signed-in-able user per role; returns its id and their emails."""
    encryption, hashing = app.state.encryption_service, app.state.hashing_service
    found: dict = {"emails": {}}

    async def seed():
        async with async_session_factory() as session:
            created = await organizations_adapter.create(session, OrganizationCreate(name=f"Acme {uuid4().hex[:6]}"))
            found["id"] = created.id
            await session.commit()
            for role in member_roles:
                address = f"{role.value}-{uuid4().hex[:6]}@acme.example"
                found["emails"][role] = address
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
                await session.commit()

    client.portal.call(seed)
    return found


def keys_path(organization_id, provider=None):
    base = f"{WEB}/staff/organizations/{organization_id}/api-keys"
    return base if provider is None else f"{base}/{provider}"


def setup_complete_for(client, email):
    """What the customer panel says about this person: whether the organization is set up."""
    client.cookies.clear()
    assert call(client, "POST", f"{WEB}/auth/login", {"email": email, "password": PASSWORD}).status_code == 200
    me = call(client, "GET", f"{WEB}/users/me")
    client.cookies.clear()
    assert me.status_code == 200, me.text
    return me.json()["setupComplete"]


def test_every_key_route_needs_a_staff_session(client):
    organization = make_organization(client)
    client.cookies.clear()

    assert call(client, "GET", keys_path(organization["id"])).status_code == 401
    assert call(client, "PUT", keys_path(organization["id"], "openai"), {"secret": SECRET}).status_code == 401
    assert call(client, "DELETE", keys_path(organization["id"], "openai")).status_code == 401


def test_a_customer_owner_cannot_set_their_own_key(client):
    organization = make_organization(client)
    client.cookies.clear()
    owner = organization["emails"][Role.OWNER]
    assert call(client, "POST", f"{WEB}/auth/login", {"email": owner, "password": PASSWORD}).status_code == 200

    assert call(client, "PUT", keys_path(organization["id"], "openai"), {"secret": SECRET}).status_code == 401
    client.cookies.clear()


def test_customers_have_no_route_for_keys_any_more(client):
    paths = [path for path in app.openapi()["paths"] if "api-keys" in path]

    assert paths
    assert all(path.startswith(f"{WEB}/staff/organizations/") for path in paths)


def test_staff_set_a_key_and_see_only_its_last_four(client, staff):
    organization = make_organization(client)

    response = call(client, "PUT", keys_path(organization["id"], "anthropic"), {"secret": SECRET})

    assert response.status_code == 200, response.text
    assert response.json()["lastFour"] == "9876"
    assert response.json()["provider"] == "anthropic"
    assert SECRET not in response.text

    listing = call(client, "GET", keys_path(organization["id"]))
    assert listing.status_code == 200
    assert [item["provider"] for item in listing.json()] == ["anthropic"]
    assert "REALLY-SECRET" not in listing.text


def test_the_secret_is_stored_encrypted(client, staff):
    organization = make_organization(client)
    call(client, "PUT", keys_path(organization["id"], "anthropic"), {"secret": SECRET})

    async def stored():
        from sqlalchemy import select

        from src.api_keys.sqlalchemy.models import ApiKeyRow

        async with async_session_factory() as session:
            rows = (await session.execute(select(ApiKeyRow).where(ApiKeyRow.organization_id == organization["id"]))).scalars().all()
            return [row.secret for row in rows]

    secrets = client.portal.call(stored)

    assert len(secrets) == 1
    assert SECRET not in secrets[0]
    assert app.state.encryption_service.decrypt(secrets[0]) == SECRET


def test_setting_a_key_again_replaces_it(client, staff):
    organization = make_organization(client)
    call(client, "PUT", keys_path(organization["id"], "openai"), {"secret": "sk-first-1111"})

    call(client, "PUT", keys_path(organization["id"], "openai"), {"secret": "sk-second-2222"})

    listing = call(client, "GET", keys_path(organization["id"])).json()
    assert [(item["provider"], item["lastFour"]) for item in listing] == [("openai", "2222")]


def test_every_user_of_the_organization_is_set_up_and_no_other_organization_is(client, staff):
    organization = make_organization(client)
    other = make_organization(client)
    assert setup_complete_for(client, organization["emails"][Role.MEMBER]) is False

    client.cookies.clear()
    assert call(client, "POST", f"{WEB}/staff/auth/login", {"email": staff, "password": PASSWORD}).status_code == 200
    assert call(client, "PUT", keys_path(organization["id"], "anthropic"), {"secret": SECRET}).status_code == 200

    assert setup_complete_for(client, organization["emails"][Role.MEMBER]) is True
    assert setup_complete_for(client, organization["emails"][Role.OWNER]) is True
    assert setup_complete_for(client, other["emails"][Role.OWNER]) is False


def test_a_cx_account_needs_its_location_id_and_shows_it_to_staff(client, staff):
    organization = make_organization(client)

    missing = call(client, "PUT", keys_path(organization["id"], "gohighlevel"), {"secret": "pit-token-abcd"})
    assert missing.status_code == 422
    assert missing.json()["code"] == "api_key_account_id_required"

    saved = call(
        client, "PUT", keys_path(organization["id"], "gohighlevel"), {"secret": "pit-token-abcd", "accountId": "loc-123"}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["accountId"] == "loc-123"
    assert "pit-token" not in saved.text


def test_a_key_set_for_an_organization_that_does_not_exist_is_not_found(client, staff):
    response = call(client, "PUT", keys_path(uuid4(), "openai"), {"secret": SECRET})

    assert response.status_code == 404
    assert response.json()["code"] == "organization_not_found"


def test_deleting_a_key_removes_only_that_provider(client, staff):
    organization = make_organization(client)
    call(client, "PUT", keys_path(organization["id"], "openai"), {"secret": "sk-openai-1111"})
    call(client, "PUT", keys_path(organization["id"], "tavily"), {"secret": "tvly-2222"})

    assert call(client, "DELETE", keys_path(organization["id"], "openai")).status_code == 200

    listing = call(client, "GET", keys_path(organization["id"])).json()
    assert [item["provider"] for item in listing] == ["tavily"]
    assert call(client, "DELETE", keys_path(organization["id"], "openai")).status_code == 404


def test_the_organization_list_says_which_organizations_can_use_the_agent(client, staff):
    organization = make_organization(client)

    def flag():
        listing = call(client, "GET", f"{WEB}/staff/organizations").json()
        return next(item for item in listing if item["id"] == str(organization["id"]))["aiEnabled"]

    assert flag() is False
    # a web search key alone does not let anyone use the agent
    call(client, "PUT", keys_path(organization["id"], "tavily"), {"secret": "tvly-2222"})
    assert flag() is False

    call(client, "PUT", keys_path(organization["id"], "openai"), {"secret": "sk-openai-1111"})
    assert flag() is True

    detail = call(client, "GET", f"{WEB}/staff/organizations/{organization['id']}").json()
    assert detail["organization"]["aiEnabled"] is True

    call(client, "DELETE", keys_path(organization["id"], "openai"))
    assert flag() is False
