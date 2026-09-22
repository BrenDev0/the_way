from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.sqlalchemy import dependencies as db_dependencies
from src.core.sessions.domain import SessionCreate
from src.core.sessions.ports import (
    CreateSessionFn,
    GetSessionByTokenHashFn,
    RevokeSessionByTokenHashFn,
    RevokeSessionFn,
    RevokeSessionsByUserIdFn,
    TouchSessionFn,
)

from . import adapter


def provide_create_session_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> CreateSessionFn:
    async def create_session_fn(session_create: SessionCreate):
        return await adapter.create(session, session_create)

    return create_session_fn


def provide_get_session_by_token_hash_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> GetSessionByTokenHashFn:
    async def get_session_by_token_hash_fn(token_hash: str):
        return await adapter.get_by_token_hash(session, token_hash)

    return get_session_by_token_hash_fn


def provide_touch_session_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> TouchSessionFn:
    async def touch_session_fn(session_id: UUID):
        return await adapter.touch(session, session_id)

    return touch_session_fn


def provide_revoke_session_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> RevokeSessionFn:
    async def revoke_session_fn(session_id: UUID):
        return await adapter.revoke(session, session_id)

    return revoke_session_fn


def provide_revoke_session_by_token_hash_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> RevokeSessionByTokenHashFn:
    async def revoke_session_by_token_hash_fn(token_hash: str):
        return await adapter.revoke_by_token_hash(session, token_hash)

    return revoke_session_by_token_hash_fn


def provide_revoke_sessions_by_user_id_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> RevokeSessionsByUserIdFn:
    async def revoke_sessions_by_user_id_fn(user_id: UUID):
        return await adapter.revoke_by_user_id(session, user_id)

    return revoke_sessions_by_user_id_fn
