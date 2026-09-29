from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.auth import dependencies as auth_dependencies
from src.projects import config, mapper
from src.projects import dependencies as projects_dependencies
from src.projects import use_cases as projects_use_cases
from src.projects.domain import Project
from src.projects.ports import ListProjectsForOrganizationFn
from src.projects.routes import (
    Bucket,
    DeleteFile,
    DeleteFolder,
    DeleteProject,
    GetFile,
    GetFolder,
    GetProject,
    ListContents,
    ListProjectFileIds,
    ListSubtreeFileIds,
    ListTree,
    UpdateProject,
)
from src.projects.schemas import (
    DeleteResponse,
    FileDownloadResponse,
    ProjectContentsResponse,
    ProjectResponse,
)
from src.users import dependencies as users_dependencies
from src.users.domain import Role, User
from src.users.ports import GetUserByIdFn

from . import use_cases as management_use_cases
from .schemas import TransferProjectRequest

router = APIRouter(tags=["projects-management"])

Manager = Annotated[User, Depends(auth_dependencies.require_role(Role.OWNER, Role.ADMIN))]


async def get_organization_project(
    project_id: UUID, current_user: Manager, get_project_fn: GetProject
) -> Project:
    return await management_use_cases.resolve_organization_project(
        project_id=project_id,
        organization_id=current_user.organization_id,
        get_project_fn=get_project_fn,
    )


OrganizationProject = Annotated[Project, Depends(get_organization_project)]


@router.get("", response_model=list[ProjectResponse])
async def list_organization_projects_route(
    current_user: Manager,
    list_projects_for_organization_fn: Annotated[
        ListProjectsForOrganizationFn,
        Depends(projects_dependencies.provide_list_projects_for_organization_fn),
    ],
    owner_id: Annotated[UUID | None, Query(alias="ownerId")] = None,
) -> list[ProjectResponse]:
    projects = await management_use_cases.list_organization_projects(
        organization_id=current_user.organization_id,
        list_projects_for_organization_fn=list_projects_for_organization_fn,
        owner_id=owner_id,
    )
    return [mapper.domain_to_project_response(project) for project in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_organization_project_route(project: OrganizationProject) -> ProjectResponse:
    return mapper.domain_to_project_response(project)


@router.get("/{project_id}/contents", response_model=ProjectContentsResponse)
async def list_organization_project_contents_route(
    project: OrganizationProject,
    get_folder_fn: GetFolder,
    list_contents_fn: ListContents,
    folder_id: Annotated[UUID | None, Query(alias="folderId")] = None,
) -> ProjectContentsResponse:
    contents = await projects_use_cases.list_contents(
        project=project,
        folder_id=folder_id,
        get_folder_fn=get_folder_fn,
        list_contents_fn=list_contents_fn,
    )
    return mapper.domain_to_contents_response(contents)


@router.get("/{project_id}/tree", response_model=ProjectContentsResponse)
async def get_organization_project_tree_route(
    project: OrganizationProject, list_tree_fn: ListTree
) -> ProjectContentsResponse:
    tree = await projects_use_cases.get_tree(project=project, list_tree_fn=list_tree_fn)
    return mapper.domain_to_contents_response(tree)


@router.get("/{project_id}/files/{file_id}/download", response_model=FileDownloadResponse)
async def download_organization_file_route(
    file_id: UUID,
    project: OrganizationProject,
    bucket_store: Bucket,
    get_file_fn: GetFile,
) -> FileDownloadResponse:
    project_file, download_url = await projects_use_cases.request_download(
        project=project,
        file_id=file_id,
        get_file_fn=get_file_fn,
        bucket_store=bucket_store,
    )
    return FileDownloadResponse(
        file=mapper.domain_to_file_response(project_file),
        download_url=download_url,
        expires_in_seconds=config.DOWNLOAD_URL_TTL_SECONDS,
    )


@router.post("/{project_id}/transfer", response_model=ProjectResponse)
async def transfer_project_route(
    payload: TransferProjectRequest,
    project: OrganizationProject,
    get_user_by_id_fn: Annotated[
        GetUserByIdFn,
        Depends(users_dependencies.provide_get_user_by_id_fn),
    ],
    update_project_fn: UpdateProject,
) -> ProjectResponse:
    transferred = await management_use_cases.transfer_project(
        project=project,
        new_owner_id=payload.new_owner_id,
        get_user_by_id_fn=get_user_by_id_fn,
        update_project_fn=update_project_fn,
    )
    return mapper.domain_to_project_response(transferred)


@router.delete("/{project_id}", response_model=DeleteResponse)
async def delete_organization_project_route(
    project: OrganizationProject,
    bucket_store: Bucket,
    list_project_file_ids_fn: ListProjectFileIds,
    delete_project_fn: DeleteProject,
) -> DeleteResponse:
    await projects_use_cases.delete_project(
        project=project,
        list_project_file_ids_fn=list_project_file_ids_fn,
        delete_project_fn=delete_project_fn,
        bucket_store=bucket_store,
    )
    return DeleteResponse(detail="Project deleted")


@router.delete("/{project_id}/folders/{folder_id}", response_model=DeleteResponse)
async def delete_organization_folder_route(
    folder_id: UUID,
    project: OrganizationProject,
    bucket_store: Bucket,
    get_folder_fn: GetFolder,
    list_subtree_file_ids_fn: ListSubtreeFileIds,
    delete_folder_fn: DeleteFolder,
) -> DeleteResponse:
    await projects_use_cases.delete_folder(
        project=project,
        folder_id=folder_id,
        get_folder_fn=get_folder_fn,
        list_subtree_file_ids_fn=list_subtree_file_ids_fn,
        delete_folder_fn=delete_folder_fn,
        bucket_store=bucket_store,
    )
    return DeleteResponse(detail="Folder deleted")


@router.delete("/{project_id}/files/{file_id}", response_model=DeleteResponse)
async def delete_organization_file_route(
    file_id: UUID,
    project: OrganizationProject,
    bucket_store: Bucket,
    get_file_fn: GetFile,
    delete_file_fn: DeleteFile,
) -> DeleteResponse:
    await projects_use_cases.delete_file(
        project=project,
        file_id=file_id,
        get_file_fn=get_file_fn,
        delete_file_fn=delete_file_fn,
        bucket_store=bucket_store,
    )
    return DeleteResponse(detail="File deleted")
