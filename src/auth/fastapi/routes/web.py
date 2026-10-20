"""Sign-in and sign-out for the front end: the session travels in an httpOnly cookie."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from src.api_keys import use_cases as api_keys_use_cases
from src.api_keys.fastapi import dependencies as api_keys_dependencies
from src.api_keys.ports import ListApiKeysForUserFn
from src.auth.fastapi.schemas import AuthUserResponse, LoginRequest, LogoutResponse
from src.auth.use_cases import sessions as sessions_use_cases
from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.exceptions import AuthenticationError
from src.fastapi import dependencies as api_dependencies
from src.sessions.config import SessionCookieConfig
from src.sessions.fastapi import dependencies as sessions_dependencies
from src.sessions.ports import CreateSessionFn, RevokeSessionByTokenHashFn
from src.sessions.tokens import SessionTokenService
from src.users.fastapi import dependencies as users_dependencies
from src.users.fastapi.schemas import UserResponse
from src.users.ports import GetUserByEmailHashFn

router = APIRouter(tags=["auth"])


@router.post("/login", response_model=AuthUserResponse)
async def login_user_route(
    payload: LoginRequest,
    response: Response,
    get_user_by_email_hash_fn: Annotated[
        GetUserByEmailHashFn,
        Depends(users_dependencies.provide_get_user_by_email_hash_fn),
    ],
    create_session_fn: Annotated[
        CreateSessionFn,
        Depends(sessions_dependencies.provide_create_session_fn),
    ],
    list_api_keys_for_user_fn: Annotated[
        ListApiKeysForUserFn,
        Depends(api_keys_dependencies.provide_list_api_keys_for_user_fn),
    ],
    hashing_service: Annotated[HashingService, Depends(api_dependencies.get_hashing_service)],
    encryption_service: Annotated[
        EncryptionService,
        Depends(api_dependencies.get_encryption_service),
    ],
    session_token_service: Annotated[
        SessionTokenService,
        Depends(api_dependencies.get_session_token_service),
    ],
    session_cookie_config: Annotated[
        SessionCookieConfig,
        Depends(api_dependencies.get_session_cookie_config),
    ],
) -> AuthUserResponse:
    user, session_token = await sessions_use_cases.login_user(
        email=payload.email,
        password=payload.password,
        get_user_by_email_hash_fn=get_user_by_email_hash_fn,
        hashing_service=hashing_service,
        create_session_fn=create_session_fn,
        session_token_service=session_token_service,
    )

    response.set_cookie(
        key=session_cookie_config.name,
        value=session_token,
        max_age=session_cookie_config.max_age_seconds,
        expires=session_cookie_config.max_age_seconds,
        path=session_cookie_config.path,
        secure=session_cookie_config.secure,
        httponly=session_cookie_config.httponly,
        samesite=session_cookie_config.samesite,
    )
    setup_complete = await api_keys_use_cases.is_setup_complete(
        user_id=user.id,
        list_api_keys_for_user_fn=list_api_keys_for_user_fn,
    )
    return AuthUserResponse(
        user=UserResponse.from_domain(
            user,
            email=encryption_service.decrypt(user.encrypted_email),
            setup_complete=setup_complete,
        )
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout_user_route(
    request: Request,
    response: Response,
    revoke_session_by_token_hash_fn: Annotated[
        RevokeSessionByTokenHashFn,
        Depends(sessions_dependencies.provide_revoke_session_by_token_hash_fn),
    ],
    session_token_service: Annotated[
        SessionTokenService,
        Depends(api_dependencies.get_session_token_service),
    ],
    session_cookie_config: Annotated[
        SessionCookieConfig,
        Depends(api_dependencies.get_session_cookie_config),
    ],
) -> LogoutResponse:
    session_token = request.cookies.get(session_cookie_config.name)
    if not session_token:
        raise AuthenticationError(message="Missing session", code="missing_session")

    await sessions_use_cases.logout_user(
        session_token=session_token,
        revoke_session_by_token_hash_fn=revoke_session_by_token_hash_fn,
        session_token_service=session_token_service,
    )

    response.delete_cookie(
        key=session_cookie_config.name,
        path=session_cookie_config.path,
        secure=session_cookie_config.secure,
        httponly=session_cookie_config.httponly,
        samesite=session_cookie_config.samesite,
    )
    return LogoutResponse(detail="Logged out")
