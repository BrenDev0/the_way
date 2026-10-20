from typing import Annotated

from fastapi import APIRouter, Depends, status

from src.projects.fastapi import dependencies as projects_dependencies
from src.projects.fastapi.dependencies import (
    Bucket,
    CurrentUser,
    DeleteProject,
    GetOrCreateLibrary,
    ListProjectFileIds,
    OwnedProject,
    ReadableProject,
    UpdateProject,
)
from src.projects.fastapi.schemas import (
    CreateProjectRequest,
    DeleteResponse,
    ProjectResponse,
    RenameRequest,
)
from src.projects.ports import CreateProjectFn, ListProjectsForOwnerFn
from src.projects.use_cases import projects as project_use_cases

router = APIRouter(tags=["projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project_route(
    payload: CreateProjectRequest,
    current_user: CurrentUser,
    list_projects_for_owner_fn: Annotated[
        ListProjectsForOwnerFn,
        Depends(projects_dependencies.provide_list_projects_for_owner_fn),
    ],
    create_project_fn: Annotated[
        CreateProjectFn,
        Depends(projects_dependencies.provide_create_project_fn),
    ],
) -> ProjectResponse:
    project = await project_use_cases.create_project(
        owner=current_user,
        name=payload.name,
        list_projects_for_owner_fn=list_projects_for_owner_fn,
        create_project_fn=create_project_fn,
    )
    return ProjectResponse.from_domain(project)


@router.get("", response_model=list[ProjectResponse])
async def list_projects_route(
    current_user: CurrentUser,
    list_projects_for_owner_fn: Annotated[
        ListProjectsForOwnerFn,
        Depends(projects_dependencies.provide_list_projects_for_owner_fn),
    ],
) -> list[ProjectResponse]:
    projects = await project_use_cases.list_projects(
        owner_id=current_user.id,
        list_projects_for_owner_fn=list_projects_for_owner_fn,
    )
    return [ProjectResponse.from_domain(project) for project in projects]


@router.get("/library", response_model=ProjectResponse)
async def get_library_route(
    current_user: CurrentUser, get_or_create_library_fn: GetOrCreateLibrary
) -> ProjectResponse:
    """The organization's library -- brand folders of logos, images and brand books --
    created the first time anyone asks. Browse and upload with the usual project routes
    and this id; changing it takes an owner or admin."""
    library = await project_use_cases.get_library(
        organization_id=current_user.organization_id,
        get_or_create_library_fn=get_or_create_library_fn,
    )
    return ProjectResponse.from_domain(library)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project_route(project: ReadableProject) -> ProjectResponse:
    return ProjectResponse.from_domain(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def rename_project_route(
    payload: RenameRequest,
    project: OwnedProject,
    update_project_fn: UpdateProject,
) -> ProjectResponse:
    renamed = await project_use_cases.rename_project(
        project=project, name=payload.name, update_project_fn=update_project_fn
    )
    return ProjectResponse.from_domain(renamed)


@router.delete("/{project_id}", response_model=DeleteResponse)
async def delete_project_route(
    project: OwnedProject,
    bucket_store: Bucket,
    list_project_file_ids_fn: ListProjectFileIds,
    delete_project_fn: DeleteProject,
) -> DeleteResponse:
    await project_use_cases.delete_project(
        project=project,
        list_project_file_ids_fn=list_project_file_ids_fn,
        delete_project_fn=delete_project_fn,
        bucket_store=bucket_store,
    )
    return DeleteResponse(detail="Project deleted")
