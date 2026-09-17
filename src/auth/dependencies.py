from typing import Annotated

from fastapi import Depends
from starlette.requests import Request

from src.api.dependencies import get_session_cookie_config, get_session_token_service
from src.core.exceptions import AuthenticationError
from src.core.sessions.config import SessionCookieConfig
from src.core.sessions.dependencies import (
    provide_get_session_by_token_hash_fn,
    provide_touch_session_fn,
)
from src.core.sessions.ports import GetSessionByTokenHashFn, TouchSessionFn
from src.core.sessions.service import validate_session_from_token
from src.core.sessions.tokens import SessionTokenService
from src.users.dependencies import provide_get_user_by_id_fn
from src.users.domain import User
from src.users.ports import GetUserByIdFn


async def get_current_user(
    request: Request,
    get_user_by_id_fn: Annotated[GetUserByIdFn, Depends(provide_get_user_by_id_fn)],
    get_session_by_token_hash_fn: Annotated[
        GetSessionByTokenHashFn,
        Depends(provide_get_session_by_token_hash_fn),
    ],
    touch_session_fn: Annotated[TouchSessionFn, Depends(provide_touch_session_fn)],
    session_token_service: Annotated[SessionTokenService, Depends(get_session_token_service)],
    session_cookie_config: Annotated[SessionCookieConfig, Depends(get_session_cookie_config)],
) -> User:
    session_token = request.cookies.get(session_cookie_config.name)
    if not session_token:
        raise AuthenticationError(message="Not authenticated", code="not_authenticated")

    session = await validate_session_from_token(
        token=session_token,
        get_session_by_token_hash_fn=get_session_by_token_hash_fn,
        touch_session_fn=touch_session_fn,
        token_service=session_token_service,
    )
    if session is None:
        raise AuthenticationError(message="Invalid session", code="invalid_session")

    user = await get_user_by_id_fn(session.user_id)
    if user is None:
        raise AuthenticationError(message="Invalid session", code="invalid_session")
    return user

