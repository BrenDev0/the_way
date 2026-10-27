from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api_keys.domain import ApiKeyCreate, Provider
from src.api_keys.ports import (
    DeleteApiKeyFn,
    ListApiKeysFn,
    ListApiKeysForUserFn,
    UpsertApiKeyFn,
)
from src.fastapi import dependencies as api_dependencies

from ..sqlalchemy import adapter


def provide_upsert_api_key_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> UpsertApiKeyFn:
    async def upsert_api_key_fn(api_key: ApiKeyCreate):
        return await adapter.upsert(session, api_key)

    return upsert_api_key_fn


def provide_list_api_keys_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> ListApiKeysFn:
    async def list_api_keys_fn(organization_id: UUID):
        return await adapter.list_for_organization(session, organization_id)

    return list_api_keys_fn


def provide_list_api_keys_for_user_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> ListApiKeysForUserFn:
    async def list_api_keys_for_user_fn(user_id: UUID):
        return await adapter.list_for_user(session, user_id)

    return list_api_keys_for_user_fn


def provide_delete_api_key_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> DeleteApiKeyFn:
    async def delete_api_key_fn(organization_id: UUID, provider: Provider):
        return await adapter.delete_for_organization(session, organization_id, provider)

    return delete_api_key_fn
