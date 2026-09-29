from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.sqlalchemy import dependencies as db_dependencies
from src.projects.domain import FolderCreate, ProjectCreate, ProjectFileCreate
from src.projects.ports import (
    CreateFileFn,
    CreateFolderFn,
    CreateProjectFn,
    DeleteFileFn,
    DeleteFolderFn,
    DeleteProjectFn,
    FindEntryFn,
    GetFileFn,
    GetFolderFn,
    GetProjectFn,
    ListContentsFn,
    ListFolderAncestorIdsFn,
    ListProjectFileIdsFn,
    ListProjectsForOrganizationFn,
    ListProjectsForOwnerFn,
    ListSubtreeFileIdsFn,
    ListTreeFn,
    UpdateFileFn,
    UpdateFolderFn,
    UpdateProjectFn,
)

from . import adapter

Session = Annotated[AsyncSession, Depends(db_dependencies.get_db_session)]


def provide_create_project_fn(session: Session) -> CreateProjectFn:
    async def create_project_fn(project: ProjectCreate):
        return await adapter.create_project(session, project)

    return create_project_fn


def provide_list_projects_for_owner_fn(session: Session) -> ListProjectsForOwnerFn:
    async def list_projects_for_owner_fn(owner_id: UUID):
        return await adapter.list_projects_for_owner(session, owner_id)

    return list_projects_for_owner_fn


def provide_list_projects_for_organization_fn(
    session: Session,
) -> ListProjectsForOrganizationFn:
    async def list_projects_for_organization_fn(
        organization_id: UUID, owner_id: UUID | None = None
    ):
        return await adapter.list_projects_for_organization(session, organization_id, owner_id)

    return list_projects_for_organization_fn


def provide_get_project_fn(session: Session) -> GetProjectFn:
    async def get_project_fn(project_id: UUID, organization_id: UUID):
        return await adapter.get_project(session, project_id, organization_id)

    return get_project_fn


def provide_update_project_fn(session: Session) -> UpdateProjectFn:
    async def update_project_fn(project_id: UUID, changes: dict[str, Any]):
        return await adapter.update_project(session, project_id, changes)

    return update_project_fn


def provide_delete_project_fn(session: Session) -> DeleteProjectFn:
    async def delete_project_fn(project_id: UUID):
        return await adapter.delete_project(session, project_id)

    return delete_project_fn


def provide_list_project_file_ids_fn(session: Session) -> ListProjectFileIdsFn:
    async def list_project_file_ids_fn(project_id: UUID):
        return await adapter.list_project_file_ids(session, project_id)

    return list_project_file_ids_fn


def provide_list_contents_fn(session: Session) -> ListContentsFn:
    async def list_contents_fn(project_id: UUID, folder_id: UUID | None):
        return await adapter.list_contents(session, project_id, folder_id)

    return list_contents_fn


def provide_list_tree_fn(session: Session) -> ListTreeFn:
    async def list_tree_fn(project_id: UUID):
        return await adapter.list_tree(session, project_id)

    return list_tree_fn


def provide_find_entry_fn(session: Session) -> FindEntryFn:
    async def find_entry_fn(project_id: UUID, folder_id: UUID | None, name: str):
        return await adapter.find_entry(session, project_id, folder_id, name)

    return find_entry_fn


def provide_create_folder_fn(session: Session) -> CreateFolderFn:
    async def create_folder_fn(folder: FolderCreate):
        return await adapter.create_folder(session, folder)

    return create_folder_fn


def provide_get_folder_fn(session: Session) -> GetFolderFn:
    async def get_folder_fn(folder_id: UUID, project_id: UUID):
        return await adapter.get_folder(session, folder_id, project_id)

    return get_folder_fn


def provide_update_folder_fn(session: Session) -> UpdateFolderFn:
    async def update_folder_fn(folder_id: UUID, changes: dict[str, Any]):
        return await adapter.update_folder(session, folder_id, changes)

    return update_folder_fn


def provide_delete_folder_fn(session: Session) -> DeleteFolderFn:
    async def delete_folder_fn(folder_id: UUID):
        return await adapter.delete_folder(session, folder_id)

    return delete_folder_fn


def provide_list_folder_ancestor_ids_fn(session: Session) -> ListFolderAncestorIdsFn:
    async def list_folder_ancestor_ids_fn(folder_id: UUID):
        return await adapter.list_folder_ancestor_ids(session, folder_id)

    return list_folder_ancestor_ids_fn


def provide_list_subtree_file_ids_fn(session: Session) -> ListSubtreeFileIdsFn:
    async def list_subtree_file_ids_fn(folder_id: UUID):
        return await adapter.list_subtree_file_ids(session, folder_id)

    return list_subtree_file_ids_fn


def provide_create_file_fn(session: Session) -> CreateFileFn:
    async def create_file_fn(project_file: ProjectFileCreate):
        return await adapter.create_file(session, project_file)

    return create_file_fn


def provide_get_file_fn(session: Session) -> GetFileFn:
    async def get_file_fn(file_id: UUID, project_id: UUID):
        return await adapter.get_file(session, file_id, project_id)

    return get_file_fn


def provide_update_file_fn(session: Session) -> UpdateFileFn:
    async def update_file_fn(file_id: UUID, changes: dict[str, Any]):
        return await adapter.update_file(session, file_id, changes)

    return update_file_fn


def provide_delete_file_fn(session: Session) -> DeleteFileFn:
    async def delete_file_fn(file_id: UUID):
        return await adapter.delete_file(session, file_id)

    return delete_file_fn
