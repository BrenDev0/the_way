"""The desktop surface end to end: the real app, real Postgres and Redis, over HTTP."""

import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api import signing
from src.api.main import app
from src.auth.cache import AuthCacheKey, build_auth_cache_key
from src.core.database.sqlalchemy.core import async_session_factory
from src.core.settings import settings
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

PASSWORD = "Sup3rSecret!pass"
DESKTOP = "/api/desktop/v1"
WEB = "/api/v1"


@pytest.fixture(scope="module")
def client():
    from src.core.database.sqlalchemy.core import engine

    with TestClient(app) as test_client:
        yield test_client
        # the pooled connections belong to the client's event loop, so close them there
        test_client.portal.call(engine.dispose)


@pytest.fixture(autouse=True)
def dispose_shared_engine():
    """Replaces the package-wide fixture, which disposes the engine on pytest's own event
    loop -- the app here runs on the test client's loop, and its connections live there."""
    yield


@pytest.fixture
def email(client):
    address = f"desk-{uuid4().hex[:10]}@example.com"
    hashing = app.state.hashing_service
    encryption = app.state.encryption_service

    async def seed():
        async with async_session_factory() as session:
            organization = await organizations_adapter.create(session, OrganizationCreate(name="Desk Co"))
            await users_adapter.create(
                session,
                UserCreate(
                    organization_id=organization.id,
                    encrypted_email=encryption.encrypt(address),
                    email_hash=hashing.deterministic_hash(address),
                    password_hash=hashing.hash_password(PASSWORD),
                    role=Role.OWNER,
                ),
            )
            await session.commit()

    async def forget_failures():
        # the test client always comes from the same address, and failures outlive a run
        await app.state.cache_store.remove(
            build_auth_cache_key(AuthCacheKey.DESKTOP_LOGIN_FAILURES_IP, "testclient")
        )

    client.portal.call(seed)
    client.portal.call(forget_failures)
    return address


def desktop_login(client, email, password=PASSWORD, device="Test laptop"):
    return client.post(
        f"{DESKTOP}/auth/login", json={"email": email, "password": password, "deviceName": device}
    )


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def signed(method, path, body=b""):
    timestamp = str(int(time.time()))
    return {
        signing.SIGNATURE_HEADER: signing.build_signature(method, path, timestamp, body),
        signing.TIMESTAMP_HEADER: timestamp,
    }


def test_login_returns_a_token_that_opens_the_desktop_api(client, email):
    login = desktop_login(client, email)

    assert login.status_code == 200, login.text
    body = login.json()
    assert body["user"]["setupComplete"] is False
    me = client.get(f"{DESKTOP}/users/me", headers=bearer(body["token"]))
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]


def test_login_never_sets_a_cookie(client, email):
    login = desktop_login(client, email)

    assert "set-cookie" not in login.headers


def test_the_desktop_api_needs_a_token(client, email):
    response = client.get(f"{DESKTOP}/users/me")

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"


def test_a_made_up_token_is_refused(client, email):
    response = client.get(f"{DESKTOP}/users/me", headers=bearer("not-a-real-token"))

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_session"


def test_a_wrong_password_is_refused_without_saying_which_part(client, email):
    response = desktop_login(client, email, password="wrong")

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_credentials"


def test_repeated_failures_are_rate_limited(client, email):
    for _ in range(settings.DESKTOP_LOGIN_MAX_FAILURES_PER_EMAIL):
        desktop_login(client, email, password="wrong")

    response = desktop_login(client, email)

    assert response.status_code == 429
    assert response.json()["code"] == "login_rate_limited"


def test_a_web_cookie_does_not_work_on_the_desktop_api(client, email):
    web_login = client.post(
        f"{WEB}/auth/login",
        json={"email": email, "password": PASSWORD},
        headers=signed("POST", f"{WEB}/auth/login", f'{{"email":"{email}","password":"{PASSWORD}"}}'.encode()),
    )
    # the signature covers the exact body bytes; fall back to letting the client encode
    if web_login.status_code != 200:
        body = f'{{"email": "{email}", "password": "{PASSWORD}"}}'.encode()
        web_login = client.post(
            f"{WEB}/auth/login",
            content=body,
            headers={**signed("POST", f"{WEB}/auth/login", body), "Content-Type": "application/json"},
        )
    assert web_login.status_code == 200, web_login.text
    cookie = web_login.cookies[settings.SESSION_COOKIE_NAME]

    as_cookie = client.get(f"{DESKTOP}/users/me", cookies={settings.SESSION_COOKIE_NAME: cookie})
    as_bearer = client.get(f"{DESKTOP}/users/me", headers=bearer(cookie))
    client.cookies.clear()

    assert as_cookie.status_code == 401
    assert as_bearer.status_code == 401
    assert as_bearer.json()["code"] == "invalid_session"


def test_a_desktop_token_does_not_work_on_the_web_api(client, email):
    token = desktop_login(client, email).json()["token"]

    unsigned = client.get(f"{WEB}/users/me", headers=bearer(token))
    signed_but_bearer = client.get(
        f"{WEB}/users/me", headers={**bearer(token), **signed("GET", f"{WEB}/users/me")}
    )
    planted_cookie = client.get(
        f"{WEB}/users/me",
        headers=signed("GET", f"{WEB}/users/me"),
        cookies={settings.SESSION_COOKIE_NAME: token},
    )
    client.cookies.clear()

    assert unsigned.json()["code"] == "request_signature_missing"
    assert signed_but_bearer.json()["code"] == "not_authenticated"
    assert planted_cookie.json()["code"] == "invalid_session"


def test_logout_revokes_the_token(client, email):
    token = desktop_login(client, email).json()["token"]

    logout = client.post(f"{DESKTOP}/auth/logout", headers=bearer(token))
    after = client.get(f"{DESKTOP}/users/me", headers=bearer(token))

    assert logout.status_code == 200
    assert after.status_code == 401


def test_a_user_sees_their_devices_and_can_sign_one_out(client, email):
    laptop = desktop_login(client, email, device="Laptop").json()["token"]
    desk = desktop_login(client, email, device="Office PC").json()["token"]

    sessions = client.get(f"{DESKTOP}/auth/sessions", headers=bearer(laptop)).json()
    by_device = {s["deviceName"]: s for s in sessions}
    assert by_device["Laptop"]["current"] is True
    assert by_device["Office PC"]["current"] is False
    assert {s["client"] for s in sessions} == {"desktop"}

    revoke = client.delete(
        f"{DESKTOP}/auth/sessions/{by_device['Office PC']['id']}", headers=bearer(laptop)
    )

    assert revoke.status_code == 200
    assert client.get(f"{DESKTOP}/users/me", headers=bearer(desk)).status_code == 401
    assert client.get(f"{DESKTOP}/users/me", headers=bearer(laptop)).status_code == 200


def test_someone_elses_session_cannot_be_signed_out(client, email):
    token = desktop_login(client, email).json()["token"]

    response = client.delete(f"{DESKTOP}/auth/sessions/{uuid4()}", headers=bearer(token))

    assert response.status_code == 404


def test_using_the_token_slides_its_expiry(client, email):
    token = desktop_login(client, email).json()["token"]
    before = client.get(f"{DESKTOP}/auth/sessions", headers=bearer(token)).json()[0]["expiresAt"]

    time.sleep(1.1)
    after = client.get(f"{DESKTOP}/auth/sessions", headers=bearer(token)).json()[0]["expiresAt"]

    assert after > before


def test_the_desktop_tool_contract_lists_every_desktop_tool(client, email):
    from src.desktop import tools as desktop_tools

    token = desktop_login(client, email).json()["token"]
    response = client.get(f"{DESKTOP}/desktop-tools", headers=bearer(token))

    assert response.status_code == 200
    by_name = {tool["name"]: tool for tool in response.json()}
    assert set(by_name) == {schema.__name__ for schema in desktop_tools.SCHEMAS}
    assert by_name["DeleteFile"]["requiresApproval"] is True
    assert by_name["ReadFile"]["requiresApproval"] is False
    assert by_name["ReadFile"]["parameters"]["required"] == ["file_path"]


def test_organization_management_is_not_on_the_desktop_api():
    desktop_paths = [path for path in app.openapi()["paths"] if path.startswith(DESKTOP)]

    for managed in ("/api-keys", "/invitations", "/projects/management", "/documents", "/skills"):
        assert not any(path.startswith(f"{DESKTOP}{managed}") for path in desktop_paths)
    assert f"{DESKTOP}/conversations/{{conversation_id}}/tool-results" in desktop_paths
