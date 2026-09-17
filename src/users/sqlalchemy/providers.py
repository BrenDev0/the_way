from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.sqlalchemy.dependencies import get_db_session
from src.users.domain import UserCreate
from src.users.ports import (
    CreateUserFn,
    DeleteUserFn,
    GetUserByEmailHashFn,
    GetUserByIdFn,
    ListUsersFn,
)
from src.users.sqlalchemy import adapters


def provide_create_user_fn(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CreateUserFn:
    async def create_user_fn(user: UserCreate):
        return await adapters.create(session, user)

    return create_user_fn


def provide_get_user_by_id_fn(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GetUserByIdFn:
    async def get_user_by_id_fn(user_id: UUID):
        return await adapters.get_user_by_id(session, user_id)

    return get_user_by_id_fn


def provide_get_user_by_email_hash_fn(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GetUserByEmailHashFn:
    async def get_user_by_email_hash_fn(email_hash: str):
        return await adapters.get_user_by_email_hash(session, email_hash)

    return get_user_by_email_hash_fn


def provide_list_users_fn(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ListUsersFn:
    async def list_users_fn():
        return await adapters.list_users(session)

    return list_users_fn


def provide_delete_user_fn(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DeleteUserFn:
    async def delete_user_fn(user_id: UUID):
        return await adapters.delete_user(session, user_id)

    return delete_user_fn
