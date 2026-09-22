from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.sqlalchemy import dependencies as db_dependencies
from src.organizations.domain import OrganizationCreate
from src.organizations.ports import (
    CreateOrganizationFn,
    DeleteOrganizationByIdFn,
    GetOrganizationByIdFn,
    UpdateOrganizationByIdFn,
)

from . import adapter


def provide_create_organization_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> CreateOrganizationFn:
    async def create_organization_fn(organization: OrganizationCreate):
        return await adapter.create(session, organization)

    return create_organization_fn


def provide_get_organization_by_id_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> GetOrganizationByIdFn:
    async def get_organization_by_id_fn(organization_id: UUID):
        return await adapter.get_by_id(session, organization_id)

    return get_organization_by_id_fn


def provide_update_organization_by_id_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> UpdateOrganizationByIdFn:
    async def update_organization_by_id_fn(organization_id: UUID, changes: dict[str, Any]):
        return await adapter.update_by_id(session, organization_id, changes)

    return update_organization_by_id_fn


def provide_delete_organization_by_id_fn(
    session: Annotated[AsyncSession, Depends(db_dependencies.get_db_session)],
) -> DeleteOrganizationByIdFn:
    async def delete_organization_by_id_fn(organization_id: UUID):
        return await adapter.delete_by_id(session, organization_id)

    return delete_organization_by_id_fn
