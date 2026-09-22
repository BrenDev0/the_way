from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

from helpers import make_session

from src.core.sessions import service as sessions_service
from src.core.sessions.domain import SessionCreate
from src.core.sessions.tokens import SessionTokenService


class TestEnsureAwareUtc:
    def test_naive_datetime_is_treated_as_utc(self):
        naive = datetime(2026, 1, 1, 12, 0)  # noqa: DTZ001 — naive is the point
        result = sessions_service.ensure_aware_utc(naive)

        assert result.tzinfo == UTC
        assert result.hour == 12

    def test_aware_datetime_is_converted_to_utc(self):
        aware = datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=3)))
        result = sessions_service.ensure_aware_utc(aware)

        assert result.tzinfo == UTC
        assert result.hour == 9


class TestCreateSession:
    async def test_stores_hashed_token_and_returns_raw_one(self):
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


class TestValidateSessionFromToken:
    def setup_method(self):
        self.token_service = SessionTokenService()
        self.touched: list = []

    async def _validate(self, session):
        async def get_by_hash(token_hash: str):
            return session

        async def touch(session_id):
            self.touched.append(session_id)
            return session

        return await sessions_service.validate_session_from_token(
            token="raw-token",
            get_session_by_token_hash_fn=get_by_hash,
            touch_session_fn=touch,
            token_service=self.token_service,
        )

    async def test_unknown_token_returns_none(self):
        assert await self._validate(None) is None
        assert self.touched == []

    async def test_revoked_session_returns_none(self):
        session = make_session(revoked_at=datetime.now(UTC))
        assert await self._validate(session) is None
        assert self.touched == []

    async def test_expired_session_returns_none(self):
        session = make_session(expires_in=timedelta(seconds=-1))
        assert await self._validate(session) is None
        assert self.touched == []

    async def test_valid_session_is_touched_and_returned(self):
        session = make_session()
        result = await self._validate(session)

        assert result is session
        assert self.touched == [session.id]

    async def test_falls_back_to_original_when_touch_returns_none(self):
        session = make_session()

        async def get_by_hash(token_hash: str):
            return session

        async def touch(session_id):
            return None

        result = await sessions_service.validate_session_from_token(
            token="raw-token",
            get_session_by_token_hash_fn=get_by_hash,
            touch_session_fn=touch,
            token_service=self.token_service,
        )
        assert result is session

    async def test_lookup_uses_the_hashed_token(self):
        seen: list[str] = []
        session = make_session()

        async def get_by_hash(token_hash: str):
            seen.append(token_hash)
            return session

        async def touch(session_id):
            return session

        await sessions_service.validate_session_from_token(
            token="raw-token",
            get_session_by_token_hash_fn=get_by_hash,
            touch_session_fn=touch,
            token_service=self.token_service,
        )
        assert seen == [self.token_service.hash_session_token("raw-token")]


class TestRevoke:
    async def test_revoke_from_token_passes_the_hash(self):
        token_service = SessionTokenService()
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

    async def test_revoke_user_sessions_returns_count(self):
        user_id = uuid4()

        async def revoke_fn(uid):
            assert uid == user_id
            return 3

        assert await sessions_service.revoke_user_sessions(user_id, revoke_fn) == 3
