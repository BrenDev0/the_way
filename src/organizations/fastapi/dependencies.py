from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.core.bucket.ports import BucketStore
from src.fastapi import dependencies as api_dependencies
from src.organizations import files as organization_files
from src.organizations.domain import FilesPurged, OrganizationCreate
from src.organizations.ports import (
    CreateOrganizationFn,
    DeleteOrganizationByIdFn,
    GetOrganizationByIdFn,
    ListMonthlyUsageFn,
    ListProjectStorageFn,
    PurgeOrganizationFilesFn,
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
        deleted = await adapter.delete_by_id(session, organization_id)
        # Committed here, not when the request ends: the caller clears the organization's files
        # next, and files must never be deleted for an organization whose rows still exist.
        await session.commit()
        return deleted

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


def provide_purge_organization_files_fn(request: Request) -> PurgeOrganizationFilesFn:
    """Clears an organization's files from the bucket. Where no bucket is configured nothing was
    ever stored, so there is nothing to clear."""
    bucket: BucketStore | None = getattr(request.app.state, "bucket_store", None)

    async def purge_organization_files_fn(organization_id: UUID) -> FilesPurged:
        if bucket is None:
            return FilesPurged(removed=0, failed=0)
        return await organization_files.purge_files(bucket, organization_id)

    return purge_organization_files_fn
