from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api_keys.domain import ApiKeyCreate
from src.api_keys.ports import (
    DeleteApiKeyForOrganizationFn,
    ListApiKeysFn,
    ListApiKeysForUserFn,
    UpsertApiKeyFn,
)
from src.core.database.sqlalchemy import dependencies as db_dependencies

from . import adapter


def provide_upsert_api_key_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> UpsertApiKeyFn:
    async def upsert_api_key_fn(api_key: ApiKeyCreate):
        return await adapter.upsert(session, api_key)

    return upsert_api_key_fn


def provide_list_api_keys_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> ListApiKeysFn:
    async def list_api_keys_fn(organization_id: UUID, user_id: UUID | None = None):
        return await adapter.list_for_organization(session, organization_id, user_id)

    return list_api_keys_fn


def provide_list_api_keys_for_user_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> ListApiKeysForUserFn:
    async def list_api_keys_for_user_fn(user_id: UUID):
        return await adapter.list_for_user(session, user_id)

    return list_api_keys_for_user_fn


def provide_delete_api_key_for_organization_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> DeleteApiKeyForOrganizationFn:
    async def delete_api_key_for_organization_fn(api_key_id: UUID, organization_id: UUID):
        return await adapter.delete_for_organization(session, api_key_id, organization_id)

    return delete_api_key_for_organization_fn
