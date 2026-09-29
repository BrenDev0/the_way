from collections.abc import Callable, Coroutine
from datetime import timedelta
from typing import Annotated

from fastapi import Depends
from starlette.requests import Request

from src.api import dependencies as api_dependencies
from src.core.cache.ports import CacheStore
from src.core.exceptions import AuthenticationError, AuthorizationError
from src.core.sessions import dependencies as sessions_dependencies
from src.core.sessions import service as sessions_service
from src.core.sessions.config import SessionCookieConfig
from src.core.sessions.domain import Session, SessionClient
from src.core.sessions.ports import (
    GetSessionByTokenHashFn,
    RenewSessionFn,
    TouchSessionFn,
)
from src.core.sessions.tokens import SessionTokenService
from src.core.settings import settings
from src.users import dependencies as users_dependencies
from src.users import use_cases as users_use_cases
from src.users.domain import Role, User
from src.users.ports import GetUserByIdFn

from . import config


def client_for(request: Request) -> SessionClient:
    """Which client a request comes from, decided by where it arrived -- never by what it
    carries, so a request cannot choose the looser of the two rules."""
    path = request.scope.get("path", "")
    return SessionClient.DESKTOP if path.startswith(config.DESKTOP_API_PREFIX) else SessionClient.WEB


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != config.BEARER_SCHEME or not token.strip():
        return None
    return token.strip()


async def get_current_session(
    request: Request,
    get_session_by_token_hash_fn: Annotated[
        GetSessionByTokenHashFn,
        Depends(sessions_dependencies.provide_get_session_by_token_hash_fn),
    ],
    touch_session_fn: Annotated[
        TouchSessionFn,
        Depends(sessions_dependencies.provide_touch_session_fn),
    ],
    renew_session_fn: Annotated[
        RenewSessionFn,
        Depends(sessions_dependencies.provide_renew_session_fn),
    ],
    session_token_service: Annotated[
        SessionTokenService,
        Depends(api_dependencies.get_session_token_service),
    ],
    session_cookie_config: Annotated[
        SessionCookieConfig,
        Depends(api_dependencies.get_session_cookie_config),
    ],
) -> Session:
    client = client_for(request)

    if client is SessionClient.DESKTOP:
        token = _bearer_token(request)
    else:
        token = request.cookies.get(session_cookie_config.name)

    if not token:
        raise AuthenticationError(message="Not authenticated", code="not_authenticated")

    # Desktop sessions slide: each request pushes the expiry out, so a device in use stays
    # signed in and one left idle for the whole window signs itself out.
    desktop = client is SessionClient.DESKTOP
    session = await sessions_service.validate_session_from_token(
        token=token,
        get_session_by_token_hash_fn=get_session_by_token_hash_fn,
        touch_session_fn=touch_session_fn,
        token_service=session_token_service,
        client=client,
        renew_session_fn=renew_session_fn if desktop else None,
        renew_ttl=timedelta(seconds=settings.DESKTOP_SESSION_TTL_SECONDS) if desktop else None,
    )
    if session is None:
        raise AuthenticationError(message="Invalid session", code="invalid_session")
    return session


async def get_current_user(
    session: Annotated[Session, Depends(get_current_session)],
    get_user_by_id_fn: Annotated[
        GetUserByIdFn,
        Depends(users_dependencies.provide_get_user_by_id_fn),
    ],
    cache_store: Annotated[CacheStore, Depends(api_dependencies.get_cache_store)],
) -> User:
    user = await users_use_cases.get_user(
        user_id=session.user_id,
        get_user_by_id_fn=get_user_by_id_fn,
        cache_store=cache_store,
    )
    if user is None:
        raise AuthenticationError(message="Invalid session", code="invalid_session")
    return user


def require_role(*allowed: Role) -> Callable[..., Coroutine[None, None, User]]:
    async def dependency(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role not in allowed:
            raise AuthorizationError(
                message="Not authorized to perform this action",
                code="insufficient_role",
            )
        return current_user

    return dependency
