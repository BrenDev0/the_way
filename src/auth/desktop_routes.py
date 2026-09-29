from typing import Annotated

from fastapi import APIRouter, Depends, Request

from src.api import dependencies as api_dependencies
from src.api_keys import dependencies as api_keys_dependencies
from src.api_keys import use_cases as api_keys_use_cases
from src.api_keys.ports import ListApiKeysForUserFn
from src.core.cache.ports import CacheStore
from src.core.cryptography.ports import EncryptionService, HashingService
from src.core.sessions import dependencies as sessions_dependencies
from src.core.sessions.domain import Session
from src.core.sessions.ports import CreateSessionFn, RevokeSessionForUserFn
from src.core.sessions.tokens import SessionTokenService
from src.users import dependencies as users_dependencies
from src.users import mapper as users_mapper
from src.users.ports import GetUserByEmailHashFn

from . import dependencies as auth_dependencies
from . import use_cases as auth_use_cases
from .schemas import DesktopLoginRequest, DesktopLoginResponse, LogoutResponse

router = APIRouter(tags=["desktop-auth"])

UNKNOWN_ADDRESS = "unknown"


@router.post("/login", response_model=DesktopLoginResponse)
async def desktop_login_route(
    payload: DesktopLoginRequest,
    request: Request,
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
    cache_store: Annotated[CacheStore, Depends(api_dependencies.get_cache_store)],
) -> DesktopLoginResponse:
    user, session, token = await auth_use_cases.login_desktop(
        email=payload.email,
        password=payload.password,
        device_name=payload.device_name,
        # Behind a proxy this is only the client's address when uvicorn trusts the
        # proxy's forwarded headers (--proxy-headers / --forwarded-allow-ips).
        client_ip=request.client.host if request.client else UNKNOWN_ADDRESS,
        get_user_by_email_hash_fn=get_user_by_email_hash_fn,
        hashing_service=hashing_service,
        create_session_fn=create_session_fn,
        session_token_service=session_token_service,
        cache_store=cache_store,
    )
    setup_complete = await api_keys_use_cases.is_setup_complete(
        user_id=user.id,
        list_api_keys_for_user_fn=list_api_keys_for_user_fn,
    )
    return DesktopLoginResponse(
        token=token,
        expires_at=session.expires_at,
        user=users_mapper.domain_to_user_response(user, encryption_service, setup_complete),
    )


@router.post("/logout", response_model=LogoutResponse)
async def desktop_logout_route(
    session: Annotated[Session, Depends(auth_dependencies.get_current_session)],
    revoke_session_for_user_fn: Annotated[
        RevokeSessionForUserFn,
        Depends(sessions_dependencies.provide_revoke_session_for_user_fn),
    ],
) -> LogoutResponse:
    await auth_use_cases.revoke_session(
        session_id=session.id,
        user_id=session.user_id,
        revoke_session_for_user_fn=revoke_session_for_user_fn,
    )
    return LogoutResponse(detail="Logged out")
