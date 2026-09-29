from datetime import UTC, datetime, timedelta
from uuid import UUID

from .domain import Session, SessionClient, SessionCreate
from .ports import (
    CreateSessionFn,
    GetSessionByTokenHashFn,
    RenewSessionFn,
    RevokeSessionByTokenHashFn,
    RevokeSessionsByUserIdFn,
    TouchSessionFn,
)
from .tokens import SessionTokenService


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def create_session(
    user_id: UUID,
    create_session_fn: CreateSessionFn,
    token_service: SessionTokenService,
    client: SessionClient = SessionClient.WEB,
    device_name: str | None = None,
    ttl: timedelta | None = None,
) -> tuple[Session, str]:
    raw_token = token_service.generate_session_token()
    token_hash = token_service.hash_session_token(raw_token)
    now = datetime.now(UTC)
    session_to_create = SessionCreate(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=now + ttl if ttl else token_service.build_expiration(now),
        last_seen_at=now,
        client=client,
        device_name=device_name,
    )
    session = await create_session_fn(session_to_create)
    return session, raw_token


async def validate_session_from_token(
    token: str,
    get_session_by_token_hash_fn: GetSessionByTokenHashFn,
    touch_session_fn: TouchSessionFn,
    token_service: SessionTokenService,
    client: SessionClient | None = None,
    renew_session_fn: RenewSessionFn | None = None,
    renew_ttl: timedelta | None = None,
) -> Session | None:
    token_hash = token_service.hash_session_token(token)
    session = await get_session_by_token_hash_fn(token_hash)
    if session is None:
        return None

    now = datetime.now(UTC)
    if session.revoked_at is not None or ensure_aware_utc(session.expires_at) <= now:
        return None

    # A token is only good on the surface it was issued for: a cookie session cannot be
    # replayed as a bearer token to skip the front end's signature, and a desktop token
    # cannot be planted as a cookie.
    if client is not None and session.client is not client:
        return None

    if renew_session_fn is not None and renew_ttl is not None:
        renewed = await renew_session_fn(session.id, now + renew_ttl)
        return renewed or session

    touched_session = await touch_session_fn(session.id)
    return touched_session or session


async def revoke_session_from_token(
    token: str,
    revoke_session_by_token_hash_fn: RevokeSessionByTokenHashFn,
    token_service: SessionTokenService,
) -> bool:
    token_hash = token_service.hash_session_token(token)
    return await revoke_session_by_token_hash_fn(token_hash)


async def revoke_user_sessions(
    user_id: UUID,
    revoke_sessions_by_user_id_fn: RevokeSessionsByUserIdFn,
) -> int:
    return await revoke_sessions_by_user_id_fn(user_id)
