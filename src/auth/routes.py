from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from src.api import dependencies as api_dependencies
from src.auth import use_cases as auth_use_cases
from src.auth.schemas import (
    AuthUserResponse,
    LoginRequest,
    LogoutResponse,
    RequestRegistrationVerificationRequest,
    RequestRegistrationVerificationResponse,
    UserRegistrationRequest,
)
from src.core.cache.ports import CacheStore
from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.exceptions import AuthenticationError
from src.core.sessions import dependencies as sessions_dependencies
from src.core.sessions.config import SessionCookieConfig
from src.core.sessions.ports import CreateSessionFn, RevokeSessionByTokenHashFn
from src.core.sessions.tokens import SessionTokenService
from src.users import dependencies as users_dependencies
from src.users.ports import CreateUserFn, GetUserByEmailHashFn
from src.users.schemas import UserResponse

router = APIRouter(tags=["auth"])


@router.post(
    "/register/request-verification",
    response_model=RequestRegistrationVerificationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_registration_verification_route(
    payload: RequestRegistrationVerificationRequest,
    cache_store: Annotated[CacheStore, Depends(api_dependencies.get_cache_store)],
    hashing_service: Annotated[HashingService, Depends(api_dependencies.get_hashing_service)],
    get_user_by_email_hash_fn: Annotated[
        GetUserByEmailHashFn,
        Depends(users_dependencies.provide_get_user_by_email_hash_fn),
    ],
) -> RequestRegistrationVerificationResponse:
    expires_at = await auth_use_cases.send_registration_verification_code(
        email=payload.email,
        cache_store=cache_store,
        hashing_service=hashing_service,
        get_user_by_email_hash_fn=get_user_by_email_hash_fn,
    )
    return RequestRegistrationVerificationResponse(
        detail="Verification code sent",
        expires_at=expires_at,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user_route(
    payload: UserRegistrationRequest,
    create_user_fn: Annotated[CreateUserFn, Depends(users_dependencies.provide_create_user_fn)],
    get_user_by_email_hash_fn: Annotated[
        GetUserByEmailHashFn,
        Depends(users_dependencies.provide_get_user_by_email_hash_fn),
    ],
    cache_store: Annotated[CacheStore, Depends(api_dependencies.get_cache_store)],
    hashing_service: Annotated[HashingService, Depends(api_dependencies.get_hashing_service)],
    encryption_service: Annotated[
        EncryptionService,
        Depends(api_dependencies.get_encryption_service),
    ],
) -> UserResponse:
    return await auth_use_cases.register_user(
        organization_id=payload.organization_id,
        email=payload.email,
        password=payload.password,
        verification_code=payload.verification_code,
        create_user_fn=create_user_fn,
        get_user_by_email_hash_fn=get_user_by_email_hash_fn,
        cache_store=cache_store,
        hashing_service=hashing_service,
        encryption_service=encryption_service,
    )


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
    user, session_token = await auth_use_cases.login_user(
        email=payload.email,
        password=payload.password,
        get_user_by_email_hash_fn=get_user_by_email_hash_fn,
        hashing_service=hashing_service,
        create_session_fn=create_session_fn,
        session_token_service=session_token_service,
        encryption_service=encryption_service,
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
    return AuthUserResponse(user=user)


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

    await auth_use_cases.logout_user(
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
