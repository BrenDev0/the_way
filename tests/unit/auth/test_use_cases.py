import pytest
from helpers import make_session, make_user

from src.auth.use_cases import sessions as sessions_use_cases
from src.core.exceptions import AuthenticationError
from src.sessions.domain import SessionCreate
from src.sessions.tokens import SessionTokenService

EMAIL = "founder@example.com"
PASSWORD = "hunter2"


@pytest.fixture
def login(hashing_service):
    async def run(user, password=PASSWORD):
        async def get_user(email_hash: str):
            return user

        async def create_session_fn(session_create: SessionCreate):
            return make_session(user_id=session_create.user_id)

        return await sessions_use_cases.login_user(
            email=EMAIL,
            password=password,
            get_user_by_email_hash_fn=get_user,
            hashing_service=hashing_service,
            create_session_fn=create_session_fn,
            session_token_service=SessionTokenService(),
        )

    return run


async def test_login_returns_the_user_and_a_session_token(login, hashing_service):
    user = make_user(password_hash=hashing_service.hash_password(PASSWORD))

    returned, token = await login(user)

    assert returned is user
    assert token


async def test_login_rejects_an_unknown_email(login):
    with pytest.raises(AuthenticationError) as exc:
        await login(None)

    assert exc.value.code == "invalid_credentials"


async def test_login_rejects_a_wrong_password(login, hashing_service):
    user = make_user(password_hash=hashing_service.hash_password(PASSWORD))

    with pytest.raises(AuthenticationError) as exc:
        await login(user, password="wrong")

    assert exc.value.code == "invalid_credentials"


async def test_login_unknown_email_and_wrong_password_look_identical(login, hashing_service):
    user = make_user(password_hash=hashing_service.hash_password(PASSWORD))

    with pytest.raises(AuthenticationError) as unknown:
        await login(None)
    with pytest.raises(AuthenticationError) as wrong:
        await login(user, password="wrong")

    assert unknown.value.code == wrong.value.code
    assert unknown.value.message == wrong.value.message


async def test_logout_revokes_the_session():
    revoked: list[str] = []

    async def revoke_fn(token_hash: str):
        revoked.append(token_hash)
        return True

    await sessions_use_cases.logout_user(
        session_token="raw-token",
        revoke_session_by_token_hash_fn=revoke_fn,
        session_token_service=SessionTokenService(),
    )

    assert len(revoked) == 1


async def test_logout_rejects_an_unknown_session():
    async def revoke_fn(token_hash: str):
        return False

    with pytest.raises(AuthenticationError):
        await sessions_use_cases.logout_user(
            session_token="raw-token",
            revoke_session_by_token_hash_fn=revoke_fn,
            session_token_service=SessionTokenService(),
        )
