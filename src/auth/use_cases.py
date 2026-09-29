from collections.abc import Sequence
from datetime import datetime, timedelta
from uuid import UUID

from src.core.cache.ports import CacheStore
from src.core.communications import service as communications_service
from src.core.communications.ports import EmailSender
from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from src.core.sessions import service as sessions_service
from src.core.sessions.domain import Session, SessionClient
from src.core.sessions.ports import (
    CreateSessionFn,
    ListActiveSessionsByUserIdFn,
    RevokeSessionByTokenHashFn,
    RevokeSessionForUserFn,
)
from src.core.sessions.tokens import SessionTokenService
from src.core.settings import settings
from src.organizations.domain import OrganizationCreate
from src.organizations.ports import CreateOrganizationFn
from src.users.domain import Role, User, UserCreate
from src.users.ports import CreateUserFn, GetUserByEmailHashFn

from . import service as auth_service


async def send_registration_verification_code(
    email: str,
    cache_store: CacheStore,
    hashing_service: HashingService,
    get_user_by_email_hash_fn: GetUserByEmailHashFn,
    email_sender: EmailSender,
) -> datetime:
    email_hash = hashing_service.deterministic_hash(email)
    existing_user = await get_user_by_email_hash_fn(email_hash)
    if existing_user is not None:
        raise ConflictError(
            message="User with this email already exists",
            code="user_email_already_exists",
        )

    raw_code, expires_at = await auth_service.issue_registration_verification_code(
        email_hash=email_hash,
        cache_store=cache_store,
        code_hash_fn=hashing_service.deterministic_hash,
    )
    await email_sender.send(communications_service.create_verification_email(raw_code, email))
    return expires_at


async def register_user(
    organization_name: str,
    email: str,
    password: str,
    verification_code: str,
    create_organization_fn: CreateOrganizationFn,
    create_user_fn: CreateUserFn,
    get_user_by_email_hash_fn: GetUserByEmailHashFn,
    cache_store: CacheStore,
    hashing_service: HashingService,
    encryption_service: EncryptionService,
) -> User:
    email_hash = hashing_service.deterministic_hash(email)
    existing_user = await get_user_by_email_hash_fn(email_hash)
    if existing_user is not None:
        raise ConflictError(
            message="User with this email already exists",
            code="user_email_already_exists",
        )

    await auth_service.verify_registration_email_code(
        email_hash=email_hash,
        submitted_code=verification_code,
        cache_store=cache_store,
        compare_code_hash_fn=lambda raw_code, stored_code_hash: hashing_service.deterministic_hash(raw_code)
        == stored_code_hash,
    )

    organization = await create_organization_fn(OrganizationCreate(name=organization_name))

    encrypted_email = encryption_service.encrypt(email)
    password_hash = hashing_service.hash_password(password)
    user_to_create = UserCreate(
        organization_id=organization.id,
        encrypted_email=encrypted_email,
        email_hash=email_hash,
        password_hash=password_hash,
        role=Role.OWNER,
    )
    return await create_user_fn(user_to_create)


def _invalid_credentials() -> AuthenticationError:
    return AuthenticationError(message="Incorrect email or password", code="invalid_credentials")


async def authenticate(
    email: str,
    password: str,
    get_user_by_email_hash_fn: GetUserByEmailHashFn,
    hashing_service: HashingService,
) -> User | None:
    """The user these credentials belong to, or None. An unknown email still pays for a
    password hash, so the response time does not reveal which emails have accounts."""
    user = await get_user_by_email_hash_fn(hashing_service.deterministic_hash(email))
    if user is None:
        hashing_service.hash_password(password)
        return None
    if not hashing_service.compare_password(password, user.password_hash):
        return None
    return user


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
        raise _invalid_credentials()

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
        raise _invalid_credentials()

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
