from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.sqlalchemy import dependencies as db_dependencies
from src.preferences.domain import PreferenceCreate
from src.preferences.ports import (
    CreatePreferenceFn,
    DeletePreferenceForUserFn,
    ListPreferencesForUserFn,
)

from . import adapter

Session = Annotated[AsyncSession, Depends(db_dependencies.get_db_session)]


def provide_create_preference_fn(session: Session) -> CreatePreferenceFn:
    async def create_preference_fn(preference: PreferenceCreate):
        return await adapter.create(session, preference)

    return create_preference_fn


def provide_list_preferences_for_user_fn(session: Session) -> ListPreferencesForUserFn:
    async def list_preferences_for_user_fn(user_id: UUID):
        return await adapter.list_for_user(session, user_id)

    return list_preferences_for_user_fn


def provide_delete_preference_for_user_fn(session: Session) -> DeletePreferenceForUserFn:
    async def delete_preference_for_user_fn(preference_id: UUID, user_id: UUID):
        return await adapter.delete_for_user(session, preference_id, user_id)

    return delete_preference_for_user_fn
