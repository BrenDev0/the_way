"""The library over HTTP: the real app, routes and roles."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.auth.cache import AuthCacheKey, build_auth_cache_key
from src.core.database.sqlalchemy.core import async_session_factory
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

PASSWORD = "Sup3rSecret!pass"
DESKTOP = "/api/desktop/v1"


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
def team(client):
    """An owner and a member of one organization, each signed in."""
    emails = {role: f"lib-{role.value}-{uuid4().hex[:8]}@example.com" for role in (Role.OWNER, Role.MEMBER)}

    async def seed():
        async with async_session_factory() as session:
            organization = await organizations_adapter.create(session, OrganizationCreate(name="Agencia"))
            for role, address in emails.items():
                await users_adapter.create(
                    session,
                    UserCreate(
                        organization_id=organization.id,
                        encrypted_email=app.state.encryption_service.encrypt(address),
                        email_hash=app.state.hashing_service.deterministic_hash(address),
                        password_hash=app.state.hashing_service.hash_password(PASSWORD),
                        role=role,
                    ),
                )
            await session.commit()

    async def forget_failures():
        await app.state.cache_store.remove(build_auth_cache_key(AuthCacheKey.DESKTOP_LOGIN_FAILURES_IP, "testclient"))

    client.portal.call(seed)
    client.portal.call(forget_failures)
    headers = {}
    for role, address in emails.items():
        response = client.post(f"{DESKTOP}/auth/login", json={"email": address, "password": PASSWORD, "deviceName": "Test laptop"})
        assert response.status_code == 200, response.text
        headers[role] = {"Authorization": f"Bearer {response.json()['token']}"}
    return headers[Role.OWNER], headers[Role.MEMBER]


def test_owners_build_the_library_and_members_only_read_it(client, team):
    owner, member = team

    library = client.get(f"{DESKTOP}/projects/library", headers=owner).json()
    assert library["shared"] is True and library["name"] == "Biblioteca"
    # the same one for everyone in the organization
    assert client.get(f"{DESKTOP}/projects/library", headers=member).json()["id"] == library["id"]
    base = f"{DESKTOP}/projects/{library['id']}"

    created = client.post(f"{base}/folders", json={"name": "Soullens"}, headers=owner)
    assert created.status_code == 201, created.text

    tree = client.get(f"{base}/tree", headers=member)
    assert tree.status_code == 200
    assert [folder["name"] for folder in tree.json()["folders"]] == ["Soullens"]

    refused = client.post(f"{base}/folders", json={"name": "Otra"}, headers=member)
    assert refused.status_code == 403
    assert refused.json()["code"] == "library_read_only"
    upload = client.post(f"{base}/files", json={"name": "x.png", "contentType": "image/png", "sizeBytes": 3}, headers=member)
    assert upload.status_code == 403

    # nobody renames or deletes the library itself, not even an owner
    assert client.delete(base, headers=owner).status_code == 404
    assert client.patch(base, json={"name": "Mía"}, headers=owner).status_code == 404
    # and it is not one of anyone's own projects
    assert library["id"] not in [p["id"] for p in client.get(f"{DESKTOP}/projects", headers=owner).json()]


def test_its_name_cannot_be_taken_by_a_project(client, team):
    owner, _ = team

    response = client.post(f"{DESKTOP}/projects", json={"name": "Biblioteca"}, headers=owner)

    assert response.status_code == 409
    assert response.json()["code"] == "project_name_reserved"
