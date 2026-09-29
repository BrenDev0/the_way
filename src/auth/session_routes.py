from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from src.core.sessions import dependencies as sessions_dependencies
from src.core.sessions.domain import Session
from src.core.sessions.ports import ListActiveSessionsByUserIdFn, RevokeSessionForUserFn

from . import dependencies as auth_dependencies
from . import use_cases as auth_use_cases
from .schemas import RevokeSessionResponse, SessionResponse

# Mounted on both surfaces: a user can see and sign out every device from the web or
# from the desktop app alike.
router = APIRouter(tags=["sessions"])

CurrentSession = Annotated[Session, Depends(auth_dependencies.get_current_session)]


@router.get("/sessions", response_model=list[SessionResponse])
async def list_sessions_route(
    current: CurrentSession,
    list_active_sessions_by_user_id_fn: Annotated[
        ListActiveSessionsByUserIdFn,
        Depends(sessions_dependencies.provide_list_active_sessions_by_user_id_fn),
    ],
) -> list[SessionResponse]:
    sessions = await auth_use_cases.list_sessions(
        user_id=current.user_id,
        list_active_sessions_by_user_id_fn=list_active_sessions_by_user_id_fn,
    )
    return [
        SessionResponse(
            id=session.id,
            client=session.client,
            device_name=session.device_name,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at,
            expires_at=session.expires_at,
            current=session.id == current.id,
        )
        for session in sessions
    ]


@router.delete("/sessions/{session_id}", response_model=RevokeSessionResponse)
async def revoke_session_route(
    session_id: UUID,
    current: CurrentSession,
    revoke_session_for_user_fn: Annotated[
        RevokeSessionForUserFn,
        Depends(sessions_dependencies.provide_revoke_session_for_user_fn),
    ],
) -> RevokeSessionResponse:
    await auth_use_cases.revoke_session(
        session_id=session_id,
        user_id=current.user_id,
        revoke_session_for_user_fn=revoke_session_for_user_fn,
    )
    return RevokeSessionResponse(detail="Session signed out")
