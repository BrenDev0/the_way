from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from helpers import make_session

from src.core.sessions import service as sessions_service
from src.core.sessions.domain import SessionCreate
from src.core.sessions.tokens import SessionTokenService


@pytest.fixture
def token_service():
    return SessionTokenService()


@pytest.fixture
def touched():
    return []


@pytest.fixture
def validate(token_service, touched):
    async def run(session, touch_result=..., seen=None):
        async def get_by_hash(token_hash: str):
            if seen is not None:
                seen.append(token_hash)
            return session

        async def touch(session_id):
            touched.append(session_id)
            return session if touch_result is ... else touch_result

        return await sessions_service.validate_session_from_token(
            token="raw-token",
            get_session_by_token_hash_fn=get_by_hash,
            touch_session_fn=touch,
            token_service=token_service,
        )

    return run


def test_naive_datetime_is_treated_as_utc():
    naive = datetime(2026, 1, 1, 12, 0)  # noqa: DTZ001
    result = sessions_service.ensure_aware_utc(naive)

    assert result.tzinfo == UTC
    assert result.hour == 12


def test_aware_datetime_is_converted_to_utc():
    aware = datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=3)))
    result = sessions_service.ensure_aware_utc(aware)

    assert result.tzinfo == UTC
    assert result.hour == 9


async def test_create_session_stores_hashed_token_and_returns_raw_one():
    created: list[SessionCreate] = []
    token_service = SessionTokenService(session_ttl=timedelta(days=1))
    user_id = uuid4()

    async def create_session_fn(session_create: SessionCreate):
        created.append(session_create)
        return make_session(user_id=session_create.user_id)

    _, raw_token = await sessions_service.create_session(
        user_id=user_id,
        create_session_fn=create_session_fn,
        token_service=token_service,
    )

    assert len(created) == 1
    assert created[0].user_id == user_id
    assert created[0].token_hash != raw_token
    assert created[0].token_hash == token_service.hash_session_token(raw_token)


async def test_unknown_token_returns_none(validate, touched):
    assert await validate(None) is None
    assert touched == []


async def test_revoked_session_returns_none(validate, touched):
    assert await validate(make_session(revoked_at=datetime.now(UTC))) is None
    assert touched == []


async def test_expired_session_returns_none(validate, touched):
    assert await validate(make_session(expires_in=timedelta(seconds=-1))) is None
    assert touched == []


async def test_valid_session_is_touched_and_returned(validate, touched):
    session = make_session()

    assert await validate(session) is session
    assert touched == [session.id]


async def test_falls_back_to_original_when_touch_returns_none(validate):
    session = make_session()

    assert await validate(session, touch_result=None) is session


async def test_lookup_uses_the_hashed_token(validate, token_service):
    seen: list[str] = []

    await validate(make_session(), seen=seen)

    assert seen == [token_service.hash_session_token("raw-token")]


async def test_revoke_from_token_passes_the_hash(token_service):
    seen: list[str] = []

    async def revoke_fn(token_hash: str):
        seen.append(token_hash)
        return True

    result = await sessions_service.revoke_session_from_token(
        token="raw-token",
        revoke_session_by_token_hash_fn=revoke_fn,
        token_service=token_service,
    )

    assert result is True
    assert seen == [token_service.hash_session_token("raw-token")]


async def test_revoke_user_sessions_returns_count():
    user_id = uuid4()

    async def revoke_fn(uid):
        assert uid == user_id
        return 3

    assert await sessions_service.revoke_user_sessions(user_id, revoke_fn) == 3
