from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from helpers import make_session, make_user

from src.auth import dependencies as auth_dependencies
from src.auth import use_cases as auth_use_cases
from src.core.exceptions import AuthenticationError, RateLimitError
from src.core.sessions import service as sessions_service
from src.core.sessions.domain import SessionClient
from src.core.sessions.tokens import SessionTokenService
from src.core.settings import settings

PASSWORD = "Sup3rSecret!"


@pytest.fixture
def user():
    return make_user(password_hash=f"pwhash::{PASSWORD}")


@pytest.fixture
def login(user, hashing_service, cache_store):
    created = []

    async def run(password=PASSWORD, email="user@example.com", ip="10.0.0.1", device="Laptop"):
        async def get_user_by_email_hash_fn(email_hash):
            return user if email_hash == "dhash::user@example.com" else None

        async def create_session_fn(session):
            created.append(session)
            return make_session(user_id=session.user_id, token_hash=session.token_hash)

        return await auth_use_cases.login_desktop(
            email=email,
            password=password,
            device_name=device,
            client_ip=ip,
            get_user_by_email_hash_fn=get_user_by_email_hash_fn,
            hashing_service=hashing_service,
            create_session_fn=create_session_fn,
            session_token_service=SessionTokenService(),
            cache_store=cache_store,
        )

    run.created = created
    return run


async def test_a_desktop_login_creates_a_desktop_session_with_its_device(login, user):
    signed_in, _, token = await login()

    created = login.created[0]
    assert signed_in is user
    assert created.client is SessionClient.DESKTOP
    assert created.device_name == "Laptop"
    assert token and created.token_hash != token


async def test_a_desktop_session_lasts_the_desktop_window(login):
    await login()

    lifetime = login.created[0].expires_at - datetime.now(UTC)
    assert lifetime > timedelta(seconds=settings.DESKTOP_SESSION_TTL_SECONDS - 60)


async def test_a_wrong_password_and_an_unknown_email_look_the_same(login):
    with pytest.raises(AuthenticationError) as wrong:
        await login(password="nope")
    with pytest.raises(AuthenticationError) as unknown:
        await login(email="nobody@example.com")

    assert wrong.value.message == unknown.value.message
    assert wrong.value.code == unknown.value.code == "invalid_credentials"


async def test_too_many_failures_for_one_email_are_refused_even_with_the_right_password(login):
    for _ in range(settings.DESKTOP_LOGIN_MAX_FAILURES_PER_EMAIL):
        with pytest.raises(AuthenticationError):
            await login(password="nope")

    with pytest.raises(RateLimitError) as exc:
        await login()

    assert exc.value.status_code == 429
    assert login.created == []


async def test_too_many_failures_from_one_address_are_refused(login):
    for n in range(settings.DESKTOP_LOGIN_MAX_FAILURES_PER_IP):
        with pytest.raises(AuthenticationError):
            await login(email=f"guess{n}@example.com")

    with pytest.raises(RateLimitError):
        await login()


async def test_another_address_is_not_blocked_by_the_first(login):
    for n in range(settings.DESKTOP_LOGIN_MAX_FAILURES_PER_IP):
        with pytest.raises(AuthenticationError):
            await login(email=f"guess{n}@example.com")

    assert (await login(ip="10.0.0.2"))[0] is not None


async def test_a_success_clears_the_email_failures(login, cache_store):
    for _ in range(settings.DESKTOP_LOGIN_MAX_FAILURES_PER_EMAIL - 1):
        with pytest.raises(AuthenticationError):
            await login(password="nope")

    await login()

    for _ in range(settings.DESKTOP_LOGIN_MAX_FAILURES_PER_EMAIL - 1):
        with pytest.raises(AuthenticationError):
            await login(password="nope")
    assert (await login())[0] is not None


async def validate(session, client, renewed=None, touched=None):
    async def get_by_hash(_token_hash):
        return session

    async def touch(session_id):
        (touched if touched is not None else []).append(session_id)
        return session

    async def renew(session_id, expires_at):
        (renewed if renewed is not None else []).append(expires_at)
        return session

    return await sessions_service.validate_session_from_token(
        token="raw",
        get_session_by_token_hash_fn=get_by_hash,
        touch_session_fn=touch,
        token_service=SessionTokenService(),
        client=client,
        renew_session_fn=renew,
        renew_ttl=timedelta(days=30),
    )


async def test_a_web_session_is_refused_where_a_desktop_one_is_expected():
    web = make_session()

    assert await validate(web, SessionClient.DESKTOP) is None


async def test_a_desktop_session_is_refused_where_a_web_one_is_expected():
    desktop = make_session()
    desktop.client = SessionClient.DESKTOP

    assert await validate(desktop, SessionClient.WEB) is None


async def test_a_desktop_session_in_use_pushes_its_expiry_out():
    desktop = make_session()
    desktop.client = SessionClient.DESKTOP
    renewed, touched = [], []

    assert await validate(desktop, SessionClient.DESKTOP, renewed, touched) is desktop
    assert renewed and renewed[0] > datetime.now(UTC) + timedelta(days=29)
    assert touched == []


@pytest.mark.parametrize(
    ("path", "client"),
    [
        ("/api/desktop/v1/users/me", SessionClient.DESKTOP),
        ("/api/v1/users/me", SessionClient.WEB),
        ("/api/v1/desktop/v1/trick", SessionClient.WEB),
    ],
)
def test_the_surface_is_decided_by_where_the_request_arrived(path, client):
    request = SimpleNamespace(scope={"path": path})

    assert auth_dependencies.client_for(request) is client  # type: ignore[arg-type]
