from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.fastapi import dependencies as api_dependencies
from src.organizations.domain import OrganizationCreate
from src.organizations.ports import (
    CreateOrganizationFn,
    DeleteOrganizationByIdFn,
    GetOrganizationByIdFn,
    ListMonthlyUsageFn,
    ListProjectStorageFn,
    UpdateOrganizationByIdFn,
)

from ..sqlalchemy import adapter, reports


def provide_create_organization_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> CreateOrganizationFn:
    async def create_organization_fn(organization: OrganizationCreate):
        return await adapter.create(session, organization)

    return create_organization_fn


def provide_get_organization_by_id_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> GetOrganizationByIdFn:
    async def get_organization_by_id_fn(organization_id: UUID):
        return await adapter.get_by_id(session, organization_id)

    return get_organization_by_id_fn


def provide_update_organization_by_id_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> UpdateOrganizationByIdFn:
    async def update_organization_by_id_fn(organization_id: UUID, changes: dict[str, Any]):
        return await adapter.update_by_id(session, organization_id, changes)

    return update_organization_by_id_fn


def provide_delete_organization_by_id_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> DeleteOrganizationByIdFn:
    async def delete_organization_by_id_fn(organization_id: UUID):
        return await adapter.delete_by_id(session, organization_id)

    return delete_organization_by_id_fn


def provide_list_project_storage_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> ListProjectStorageFn:
    async def list_project_storage_fn(organization_id: UUID):
        return await reports.list_project_storage(session, organization_id)

    return list_project_storage_fn


def provide_list_monthly_usage_fn(
    session: Annotated[AsyncSession, Depends(api_dependencies.get_db_session)],
) -> ListMonthlyUsageFn:
    async def list_monthly_usage_fn(organization_id: UUID, since: datetime):
        return await reports.list_monthly_usage(session, organization_id, since)

    return list_monthly_usage_fn
