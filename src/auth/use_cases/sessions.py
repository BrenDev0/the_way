from collections.abc import Sequence
from datetime import timedelta
from uuid import UUID

from src.auth import service as auth_service
from src.core.cache.ports import CacheStore
from src.core.cryptography.ports import HashingService
from src.core.exceptions import AuthenticationError, NotFoundError
from src.core.settings import settings
from src.sessions import service as sessions_service
from src.sessions.domain import Session, SessionClient
from src.sessions.ports import (
    CreateSessionFn,
    ListActiveSessionsByUserIdFn,
    RevokeSessionByTokenHashFn,
    RevokeSessionForUserFn,
)
from src.sessions.tokens import SessionTokenService
from src.users.domain import User
from src.users.ports import GetUserByEmailHashFn

from .common import authenticate, invalid_credentials


async def login_user(
    email: str,
    password: str,
    get_user_by_email_hash_fn: GetUserByEmailHashFn,
    hashing_service: HashingService,
    create_session_fn: CreateSessionFn,
    session_token_service: SessionTokenService,
) -> tuple[User, str]:
    user = await authenticate(email, password, get_user_by_email_hash_fn, hashing_service)
    if user is None:
        raise invalid_credentials()

    _, raw_session_token = await sessions_service.create_session(
        user_id=user.id,
        create_session_fn=create_session_fn,
        token_service=session_token_service,
    )
    return user, raw_session_token


async def login_desktop(
    email: str,
    password: str,
    device_name: str | None,
    client_ip: str,
    get_user_by_email_hash_fn: GetUserByEmailHashFn,
    hashing_service: HashingService,
    create_session_fn: CreateSessionFn,
    session_token_service: SessionTokenService,
    cache_store: CacheStore,
) -> tuple[User, Session, str]:
    """Sign the desktop app in: a desktop session whose token is handed back to the app
    rather than set as a cookie, rate limited because nothing stands in front of it."""
    email_hash = hashing_service.deterministic_hash(email)
    await auth_service.ensure_desktop_login_allowed(email_hash, client_ip, cache_store)

    user = await authenticate(email, password, get_user_by_email_hash_fn, hashing_service)
    if user is None:
        await auth_service.record_desktop_login_failure(email_hash, client_ip, cache_store)
        raise invalid_credentials()

    await auth_service.clear_desktop_login_failures(email_hash, cache_store)
    session, raw_token = await sessions_service.create_session(
        user_id=user.id,
        create_session_fn=create_session_fn,
        token_service=session_token_service,
        client=SessionClient.DESKTOP,
        device_name=(device_name or "").strip()[:100] or None,
        ttl=timedelta(seconds=settings.DESKTOP_SESSION_TTL_SECONDS),
    )
    return user, session, raw_token


async def list_sessions(
    user_id: UUID,
    list_active_sessions_by_user_id_fn: ListActiveSessionsByUserIdFn,
) -> Sequence[Session]:
    return await list_active_sessions_by_user_id_fn(user_id)


async def revoke_session(
    session_id: UUID,
    user_id: UUID,
    revoke_session_for_user_fn: RevokeSessionForUserFn,
) -> None:
    if not await revoke_session_for_user_fn(session_id, user_id):
        raise NotFoundError(message="Session not found", code="session_not_found")


async def logout_user(
    session_token: str,
    revoke_session_by_token_hash_fn: RevokeSessionByTokenHashFn,
    session_token_service: SessionTokenService,
) -> None:
    revoked = await sessions_service.revoke_session_from_token(
        token=session_token,
        revoke_session_by_token_hash_fn=revoke_session_by_token_hash_fn,
        token_service=session_token_service,
    )
    if not revoked:
        raise AuthenticationError(message="Session not found", code="session_not_found")
