from typing import Annotated

from fastapi import APIRouter, Depends, Response

from src.api import dependencies as api_dependencies
from src.auth import dependencies as auth_dependencies
from src.core.cache.ports import CacheStore
from src.core.cryptography.ports import EncryptionService
from src.core.sessions import dependencies as sessions_dependencies
from src.core.sessions.config import SessionCookieConfig
from src.core.sessions.ports import RevokeSessionsByUserIdFn

from . import dependencies as users_dependencies
from . import mapper
from . import use_cases as users_use_cases
from .domain import Role, User
from .ports import DeleteUserFn, ListUsersFn
from .schemas import DeleteUserResponse, UserResponse

router = APIRouter(tags=["users"])


@router.delete("/me", response_model=DeleteUserResponse)
async def delete_current_user_route(
    response: Response,
    current_user: Annotated[User, Depends(auth_dependencies.get_current_user)],
    delete_user_fn: Annotated[DeleteUserFn, Depends(users_dependencies.provide_delete_user_fn)],
    revoke_sessions_by_user_id_fn: Annotated[
        RevokeSessionsByUserIdFn,
        Depends(sessions_dependencies.provide_revoke_sessions_by_user_id_fn),
    ],
    cache_store: Annotated[CacheStore, Depends(api_dependencies.get_cache_store)],
    session_cookie_config: Annotated[
        SessionCookieConfig,
        Depends(api_dependencies.get_session_cookie_config),
    ],
) -> DeleteUserResponse:
    await users_use_cases.delete_user(
        user_id=current_user.id,
        role=current_user.role,
        delete_user_fn=delete_user_fn,
        revoke_sessions_by_user_id_fn=revoke_sessions_by_user_id_fn,
        cache_store=cache_store,
    )

    response.delete_cookie(
        key=session_cookie_config.name,
        path=session_cookie_config.path,
        secure=session_cookie_config.secure,
        httponly=session_cookie_config.httponly,
        samesite=session_cookie_config.samesite,
    )
    return DeleteUserResponse(detail="Account deleted")


@router.get("", response_model=list[UserResponse])
async def list_users_route(
    current_user: Annotated[
        User,
        Depends(auth_dependencies.require_role(Role.OWNER, Role.ADMIN)),
    ],
    list_users_fn: Annotated[ListUsersFn, Depends(users_dependencies.provide_list_users_fn)],
    encryption_service: Annotated[
        EncryptionService,
        Depends(api_dependencies.get_encryption_service),
    ],
) -> list[UserResponse]:
    users = await users_use_cases.list_users(
        organization_id=current_user.organization_id,
        list_users_fn=list_users_fn,
    )
    return [mapper.domain_to_user_response(user, encryption_service) for user in users]
