from typing import Annotated

from fastapi import APIRouter, Depends, Response

from src.api.dependencies import get_session_cookie_config
from src.auth.dependencies import get_current_user
from src.core.sessions.config import SessionCookieConfig
from src.core.sessions.dependencies import provide_revoke_sessions_by_user_id_fn
from src.core.sessions.ports import RevokeSessionsByUserIdFn
from src.users.dependencies import provide_delete_user_fn
from src.users.domain import User
from src.users.ports import DeleteUserFn
from src.users.schemas import DeleteUserResponse
from src.users.use_cases import delete_user

router = APIRouter(tags=["users"])


@router.delete("/me", response_model=DeleteUserResponse)
async def delete_current_user_route(
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    delete_user_fn: Annotated[DeleteUserFn, Depends(provide_delete_user_fn)],
    revoke_sessions_by_user_id_fn: Annotated[
        RevokeSessionsByUserIdFn,
        Depends(provide_revoke_sessions_by_user_id_fn),
    ],
    session_cookie_config: Annotated[SessionCookieConfig, Depends(get_session_cookie_config)],
) -> DeleteUserResponse:
    await delete_user(
        user_id=current_user.id,
        delete_user_fn=delete_user_fn,
        revoke_sessions_by_user_id_fn=revoke_sessions_by_user_id_fn,
    )

    response.delete_cookie(
        key=session_cookie_config.name,
        path=session_cookie_config.path,
        secure=session_cookie_config.secure,
        httponly=session_cookie_config.httponly,
        samesite=session_cookie_config.samesite,
    )
    return DeleteUserResponse(detail="Account deleted")
