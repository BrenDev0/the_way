from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from src.api.dependencies import (
    get_cache_store,
    get_encryption_service,
    get_hashing_service,
    get_session_cookie_config,
    get_session_token_service,
)
from src.auth.schemas import (
    AuthUserResponse,
    LoginRequest,
    LogoutResponse,
    RequestRegistrationVerificationRequest,
    RequestRegistrationVerificationResponse,
    UserRegistrationRequest,
)
from src.auth.use_cases import (
    login_user,
    logout_user,
    register_user,
    send_registration_verification_code,
)
from src.core.cache.ports import CacheStore
from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.exceptions import AuthenticationError
from src.core.sessions.config import SessionCookieConfig
from src.core.sessions.dependencies import (
    provide_create_session_fn,
    provide_revoke_session_by_token_hash_fn,
)
from src.core.sessions.ports import CreateSessionFn, RevokeSessionByTokenHashFn
from src.core.sessions.tokens import SessionTokenService
from src.users.dependencies import provide_create_user_fn, provide_get_user_by_email_hash_fn
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
    cache_store: Annotated[CacheStore, Depends(get_cache_store)],
    hashing_service: Annotated[HashingService, Depends(get_hashing_service)],
    get_user_by_email_hash_fn: Annotated[
        GetUserByEmailHashFn,
        Depends(provide_get_user_by_email_hash_fn),
    ],
) -> RequestRegistrationVerificationResponse:
    expires_at = await send_registration_verification_code(
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
    create_user_fn: Annotated[CreateUserFn, Depends(provide_create_user_fn)],
    get_user_by_email_hash_fn: Annotated[
        GetUserByEmailHashFn,
        Depends(provide_get_user_by_email_hash_fn),
    ],
    cache_store: Annotated[CacheStore, Depends(get_cache_store)],
    hashing_service: Annotated[HashingService, Depends(get_hashing_service)],
    encryption_service: Annotated[EncryptionService, Depends(get_encryption_service)],
) -> UserResponse:
    return await register_user(
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
        Depends(provide_get_user_by_email_hash_fn),
    ],
    create_session_fn: Annotated[CreateSessionFn, Depends(provide_create_session_fn)],
    hashing_service: Annotated[HashingService, Depends(get_hashing_service)],
    encryption_service: Annotated[EncryptionService, Depends(get_encryption_service)],
    session_token_service: Annotated[SessionTokenService, Depends(get_session_token_service)],
    session_cookie_config: Annotated[SessionCookieConfig, Depends(get_session_cookie_config)],
) -> AuthUserResponse:
    user, session_token = await login_user(
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
        Depends(provide_revoke_session_by_token_hash_fn),
    ],
    session_token_service: Annotated[SessionTokenService, Depends(get_session_token_service)],
    session_cookie_config: Annotated[SessionCookieConfig, Depends(get_session_cookie_config)],
) -> LogoutResponse:
    session_token = request.cookies.get(session_cookie_config.name)
    if not session_token:
        raise AuthenticationError(message="Missing session", code="missing_session")

    await logout_user(
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
