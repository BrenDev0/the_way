from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth.fastapi import dependencies as auth_dependencies
from src.core.bucket.ports import BucketStore
from src.fastapi import dependencies as api_dependencies
from src.users.domain import User

from ..domain import FolderCreate, Project, ProjectCreate, ProjectFileCreate
from ..ports import (
    CreateFileFn,
    CreateFolderFn,
    CreateProjectFn,
    DeleteFileFn,
    DeleteFolderFn,
    DeleteProjectFn,
    FindEntryFn,
    GetFileFn,
    GetFileWithProjectFn,
    GetFolderFn,
    GetLibraryFn,
    GetOrCreateLibraryFn,
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
from ..sqlalchemy import adapter
from ..use_cases import projects as project_use_cases

Session = Annotated[AsyncSession, Depends(api_dependencies.get_db_session)]


# --- the ports, backed by the SQLAlchemy adapter ------------------------------------


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


def provide_get_library_fn(session: Session) -> GetLibraryFn:
    async def get_library_fn(organization_id: UUID):
        return await adapter.get_library(session, organization_id)

    return get_library_fn


def provide_get_or_create_library_fn(session: Session) -> GetOrCreateLibraryFn:
    async def get_or_create_library_fn(organization_id: UUID, name: str):
        return await adapter.get_or_create_library(session, organization_id, name)

    return get_or_create_library_fn


def provide_get_file_with_project_fn(session: Session) -> GetFileWithProjectFn:
    async def get_file_with_project_fn(file_id: UUID):
        return await adapter.get_file_with_project(session, file_id)

    return get_file_with_project_fn


# --- what the routes of this slice -- the member's own and the manager's -- share -----

Bucket = Annotated[BucketStore, Depends(api_dependencies.get_bucket_store)]

GetProject = Annotated[GetProjectFn, Depends(provide_get_project_fn)]
UpdateProject = Annotated[UpdateProjectFn, Depends(provide_update_project_fn)]
DeleteProject = Annotated[DeleteProjectFn, Depends(provide_delete_project_fn)]
ListProjectFileIds = Annotated[ListProjectFileIdsFn, Depends(provide_list_project_file_ids_fn)]
ListContents = Annotated[ListContentsFn, Depends(provide_list_contents_fn)]
ListTree = Annotated[ListTreeFn, Depends(provide_list_tree_fn)]
FindEntry = Annotated[FindEntryFn, Depends(provide_find_entry_fn)]
GetFolder = Annotated[GetFolderFn, Depends(provide_get_folder_fn)]
CreateFolder = Annotated[CreateFolderFn, Depends(provide_create_folder_fn)]
UpdateFolder = Annotated[UpdateFolderFn, Depends(provide_update_folder_fn)]
DeleteFolder = Annotated[DeleteFolderFn, Depends(provide_delete_folder_fn)]
ListFolderAncestorIds = Annotated[
    ListFolderAncestorIdsFn, Depends(provide_list_folder_ancestor_ids_fn)
]
ListSubtreeFileIds = Annotated[ListSubtreeFileIdsFn, Depends(provide_list_subtree_file_ids_fn)]
GetFile = Annotated[GetFileFn, Depends(provide_get_file_fn)]
CreateFile = Annotated[CreateFileFn, Depends(provide_create_file_fn)]
UpdateFile = Annotated[UpdateFileFn, Depends(provide_update_file_fn)]
DeleteFile = Annotated[DeleteFileFn, Depends(provide_delete_file_fn)]
GetOrCreateLibrary = Annotated[GetOrCreateLibraryFn, Depends(provide_get_or_create_library_fn)]
GetFileWithProject = Annotated[GetFileWithProjectFn, Depends(provide_get_file_with_project_fn)]

CurrentUser = Annotated[User, Depends(auth_dependencies.get_current_user)]


async def get_owned_project(
    project_id: UUID, current_user: CurrentUser, get_project_fn: GetProject
) -> Project:
    return await project_use_cases.resolve_owned_project(
        project_id=project_id, user=current_user, get_project_fn=get_project_fn
    )


async def get_readable_project(
    project_id: UUID, current_user: CurrentUser, get_project_fn: GetProject
) -> Project:
    return await project_use_cases.resolve_readable_project(
        project_id=project_id, user=current_user, get_project_fn=get_project_fn
    )


async def get_writable_project(
    project_id: UUID, current_user: CurrentUser, get_project_fn: GetProject
) -> Project:
    return await project_use_cases.resolve_writable_project(
        project_id=project_id, user=current_user, get_project_fn=get_project_fn
    )


# Own projects, plus the organization's library: every member reads it, owners and admins
# change it. Renaming or deleting a project stays with OwnedProject -- the library is no one's.
OwnedProject = Annotated[Project, Depends(get_owned_project)]
ReadableProject = Annotated[Project, Depends(get_readable_project)]
WritableProject = Annotated[Project, Depends(get_writable_project)]
