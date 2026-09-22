from collections.abc import Callable, Coroutine
from typing import Annotated

from fastapi import Depends
from starlette.requests import Request

from src.api import dependencies as api_dependencies
from src.core.cache.ports import CacheStore
from src.core.exceptions import AuthenticationError, AuthorizationError
from src.core.sessions import dependencies as sessions_dependencies
from src.core.sessions import service as sessions_service
from src.core.sessions.config import SessionCookieConfig
from src.core.sessions.ports import GetSessionByTokenHashFn, TouchSessionFn
from src.core.sessions.tokens import SessionTokenService
from src.users import dependencies as users_dependencies
from src.users import use_cases as users_use_cases
from src.users.domain import Role, User
from src.users.ports import GetUserByIdFn


async def get_current_user(
    request: Request,
    get_user_by_id_fn: Annotated[
        GetUserByIdFn,
        Depends(users_dependencies.provide_get_user_by_id_fn),
    ],
    get_session_by_token_hash_fn: Annotated[
        GetSessionByTokenHashFn,
        Depends(sessions_dependencies.provide_get_session_by_token_hash_fn),
    ],
    touch_session_fn: Annotated[
        TouchSessionFn,
        Depends(sessions_dependencies.provide_touch_session_fn),
    ],
    session_token_service: Annotated[
        SessionTokenService,
        Depends(api_dependencies.get_session_token_service),
    ],
    session_cookie_config: Annotated[
        SessionCookieConfig,
        Depends(api_dependencies.get_session_cookie_config),
    ],
    cache_store: Annotated[CacheStore, Depends(api_dependencies.get_cache_store)],
) -> User:
    session_token = request.cookies.get(session_cookie_config.name)
    if not session_token:
        raise AuthenticationError(message="Not authenticated", code="not_authenticated")

    session = await sessions_service.validate_session_from_token(
        token=session_token,
        get_session_by_token_hash_fn=get_session_by_token_hash_fn,
        touch_session_fn=touch_session_fn,
        token_service=session_token_service,
    )
    if session is None:
        raise AuthenticationError(message="Invalid session", code="invalid_session")

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

