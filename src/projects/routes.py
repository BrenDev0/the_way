from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api import dependencies as api_dependencies
from src.auth import dependencies as auth_dependencies
from src.core.database.sqlalchemy.dependencies import get_db_session
from src.core.bucket.ports import BucketStore
from src.users.domain import User

from . import config, mapper
from . import dependencies as projects_dependencies
from . import use_cases as projects_use_cases
from .domain import Project
from .sqlalchemy import adapter as projects_adapter
from .ports import (
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
    ListProjectsForOwnerFn,
    ListSubtreeFileIdsFn,
    ListTreeFn,
    UpdateFileFn,
    UpdateFolderFn,
    UpdateProjectFn,
)
from .schemas import (
    CreateFolderRequest,
    CreateProjectRequest,
    DeleteResponse,
    FileDownloadResponse,
    FileResponse,
    FileUploadTicketResponse,
    FolderResponse,
    MoveFileRequest,
    MoveFolderRequest,
    ProjectContentsResponse,
    ProjectResponse,
    RenameRequest,
    RequestFileUploadRequest,
)

router = APIRouter(tags=["projects"])

CurrentUser = Annotated[User, Depends(auth_dependencies.get_current_user)]
Bucket = Annotated[BucketStore, Depends(api_dependencies.get_bucket_store)]
Session = Annotated[AsyncSession, Depends(get_db_session)]

GetProject = Annotated[GetProjectFn, Depends(projects_dependencies.provide_get_project_fn)]
UpdateProject = Annotated[
    UpdateProjectFn, Depends(projects_dependencies.provide_update_project_fn)
]
DeleteProject = Annotated[
    DeleteProjectFn, Depends(projects_dependencies.provide_delete_project_fn)
]
ListProjectFileIds = Annotated[
    ListProjectFileIdsFn, Depends(projects_dependencies.provide_list_project_file_ids_fn)
]
ListContents = Annotated[ListContentsFn, Depends(projects_dependencies.provide_list_contents_fn)]
ListTree = Annotated[ListTreeFn, Depends(projects_dependencies.provide_list_tree_fn)]
FindEntry = Annotated[FindEntryFn, Depends(projects_dependencies.provide_find_entry_fn)]
GetFolder = Annotated[GetFolderFn, Depends(projects_dependencies.provide_get_folder_fn)]
CreateFolder = Annotated[
    CreateFolderFn, Depends(projects_dependencies.provide_create_folder_fn)
]
UpdateFolder = Annotated[
    UpdateFolderFn, Depends(projects_dependencies.provide_update_folder_fn)
]
DeleteFolder = Annotated[
    DeleteFolderFn, Depends(projects_dependencies.provide_delete_folder_fn)
]
ListFolderAncestorIds = Annotated[
    ListFolderAncestorIdsFn,
    Depends(projects_dependencies.provide_list_folder_ancestor_ids_fn),
]
ListSubtreeFileIds = Annotated[
    ListSubtreeFileIdsFn, Depends(projects_dependencies.provide_list_subtree_file_ids_fn)
]
GetFile = Annotated[GetFileFn, Depends(projects_dependencies.provide_get_file_fn)]
CreateFile = Annotated[CreateFileFn, Depends(projects_dependencies.provide_create_file_fn)]
UpdateFile = Annotated[UpdateFileFn, Depends(projects_dependencies.provide_update_file_fn)]
DeleteFile = Annotated[DeleteFileFn, Depends(projects_dependencies.provide_delete_file_fn)]


async def get_owned_project(
    project_id: UUID, current_user: CurrentUser, get_project_fn: GetProject
) -> Project:
    return await projects_use_cases.resolve_owned_project(
        project_id=project_id, user=current_user, get_project_fn=get_project_fn
    )


OwnedProject = Annotated[Project, Depends(get_owned_project)]


async def get_readable_project(
    project_id: UUID, current_user: CurrentUser, get_project_fn: GetProject
) -> Project:
    return await projects_use_cases.resolve_readable_project(
        project_id=project_id, user=current_user, get_project_fn=get_project_fn
    )


async def get_writable_project(
    project_id: UUID, current_user: CurrentUser, get_project_fn: GetProject
) -> Project:
    return await projects_use_cases.resolve_writable_project(
        project_id=project_id, user=current_user, get_project_fn=get_project_fn
    )


# Own projects, plus the organization's library: every member reads it, owners and admins
# change it. Renaming or deleting a project stays with OwnedProject -- the library is no one's.
ReadableProject = Annotated[Project, Depends(get_readable_project)]
WritableProject = Annotated[Project, Depends(get_writable_project)]


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
    project = await projects_use_cases.create_project(
        owner=current_user,
        name=payload.name,
        list_projects_for_owner_fn=list_projects_for_owner_fn,
        create_project_fn=create_project_fn,
    )
    return mapper.domain_to_project_response(project)


@router.get("", response_model=list[ProjectResponse])
async def list_projects_route(
    current_user: CurrentUser,
    list_projects_for_owner_fn: Annotated[
        ListProjectsForOwnerFn,
        Depends(projects_dependencies.provide_list_projects_for_owner_fn),
    ],
) -> list[ProjectResponse]:
    projects = await projects_use_cases.list_projects(
        owner_id=current_user.id,
        list_projects_for_owner_fn=list_projects_for_owner_fn,
    )
    return [mapper.domain_to_project_response(project) for project in projects]


@router.get("/library", response_model=ProjectResponse)
async def get_library_route(current_user: CurrentUser, session: Session) -> ProjectResponse:
    """The organization's library -- brand folders of logos, images and brand books --
    created the first time anyone asks. Browse and upload with the usual project routes
    and this id; changing it takes an owner or admin."""
    library = await projects_adapter.get_or_create_library(
        session, current_user.organization_id, config.LIBRARY_PROJECT
    )
    return mapper.domain_to_project_response(library)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project_route(project: ReadableProject) -> ProjectResponse:
    return mapper.domain_to_project_response(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def rename_project_route(
    payload: RenameRequest,
    project: OwnedProject,
    update_project_fn: UpdateProject,
) -> ProjectResponse:
    renamed = await projects_use_cases.rename_project(
        project=project, name=payload.name, update_project_fn=update_project_fn
    )
    return mapper.domain_to_project_response(renamed)


@router.delete("/{project_id}", response_model=DeleteResponse)
async def delete_project_route(
    project: OwnedProject,
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


@router.get("/{project_id}/contents", response_model=ProjectContentsResponse)
async def list_contents_route(
    project: ReadableProject,
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
async def get_tree_route(project: ReadableProject, list_tree_fn: ListTree) -> ProjectContentsResponse:
    tree = await projects_use_cases.get_tree(project=project, list_tree_fn=list_tree_fn)
    return mapper.domain_to_contents_response(tree)


@router.post(
    "/{project_id}/folders",
    response_model=FolderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder_route(
    payload: CreateFolderRequest,
    project: WritableProject,
    get_folder_fn: GetFolder,
    find_entry_fn: FindEntry,
    create_folder_fn: CreateFolder,
) -> FolderResponse:
    folder = await projects_use_cases.create_folder(
        project=project,
        name=payload.name,
        parent_id=payload.parent_id,
        get_folder_fn=get_folder_fn,
        find_entry_fn=find_entry_fn,
        create_folder_fn=create_folder_fn,
    )
    return mapper.domain_to_folder_response(folder)


@router.patch("/{project_id}/folders/{folder_id}", response_model=FolderResponse)
async def rename_folder_route(
    folder_id: UUID,
    payload: RenameRequest,
    project: WritableProject,
    get_folder_fn: GetFolder,
    find_entry_fn: FindEntry,
    update_folder_fn: UpdateFolder,
) -> FolderResponse:
    folder = await projects_use_cases.rename_folder(
        project=project,
        folder_id=folder_id,
        name=payload.name,
        get_folder_fn=get_folder_fn,
        find_entry_fn=find_entry_fn,
        update_folder_fn=update_folder_fn,
    )
    return mapper.domain_to_folder_response(folder)


@router.post("/{project_id}/folders/{folder_id}/move", response_model=FolderResponse)
async def move_folder_route(
    folder_id: UUID,
    payload: MoveFolderRequest,
    project: WritableProject,
    get_folder_fn: GetFolder,
    list_folder_ancestor_ids_fn: ListFolderAncestorIds,
    find_entry_fn: FindEntry,
    update_folder_fn: UpdateFolder,
) -> FolderResponse:
    folder = await projects_use_cases.move_folder(
        project=project,
        folder_id=folder_id,
        parent_id=payload.parent_id,
        get_folder_fn=get_folder_fn,
        list_folder_ancestor_ids_fn=list_folder_ancestor_ids_fn,
        find_entry_fn=find_entry_fn,
        update_folder_fn=update_folder_fn,
    )
    return mapper.domain_to_folder_response(folder)


@router.delete("/{project_id}/folders/{folder_id}", response_model=DeleteResponse)
async def delete_folder_route(
    folder_id: UUID,
    project: WritableProject,
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


@router.post(
    "/{project_id}/files",
    response_model=FileUploadTicketResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_upload_route(
    payload: RequestFileUploadRequest,
    project: WritableProject,
    current_user: CurrentUser,
    bucket_store: Bucket,
    get_folder_fn: GetFolder,
    find_entry_fn: FindEntry,
    delete_file_fn: DeleteFile,
    create_file_fn: CreateFile,
) -> FileUploadTicketResponse:
    project_file, upload_url = await projects_use_cases.request_upload(
        project=project,
        name=payload.name,
        folder_id=payload.folder_id,
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        uploaded_by=current_user.id,
        get_folder_fn=get_folder_fn,
        find_entry_fn=find_entry_fn,
        delete_file_fn=delete_file_fn,
        create_file_fn=create_file_fn,
        bucket_store=bucket_store,
    )
    return FileUploadTicketResponse(
        file=mapper.domain_to_file_response(project_file),
        upload_url=upload_url,
        expires_in_seconds=config.UPLOAD_URL_TTL_SECONDS,
    )


@router.post("/{project_id}/files/{file_id}/complete", response_model=FileResponse)
async def complete_upload_route(
    file_id: UUID,
    project: WritableProject,
    bucket_store: Bucket,
    get_file_fn: GetFile,
    update_file_fn: UpdateFile,
) -> FileResponse:
    project_file = await projects_use_cases.complete_upload(
        project=project,
        file_id=file_id,
        get_file_fn=get_file_fn,
        update_file_fn=update_file_fn,
        bucket_store=bucket_store,
    )
    return mapper.domain_to_file_response(project_file)


@router.get("/{project_id}/files/{file_id}/download", response_model=FileDownloadResponse)
async def request_download_route(
    file_id: UUID,
    project: ReadableProject,
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


@router.get("/{project_id}/files/{file_id}/content")
async def file_content_route(
    file_id: UUID,
    project: ReadableProject,
    bucket_store: Bucket,
    get_file_fn: GetFile,
) -> Response:
    """The file itself, with its own content type -- for opening it in the app or saving it,
    from wherever the client is: the server fetches it from the bucket."""
    project_file, content = await projects_use_cases.read_file(
        project=project, file_id=file_id, get_file_fn=get_file_fn, bucket_store=bucket_store
    )
    return Response(
        content=content,
        media_type=project_file.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(project_file.name)}",
            # it is opened inside the app; nothing it contains should run as a page of ours
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.patch("/{project_id}/files/{file_id}", response_model=FileResponse)
async def rename_file_route(
    file_id: UUID,
    payload: RenameRequest,
    project: WritableProject,
    get_file_fn: GetFile,
    find_entry_fn: FindEntry,
    update_file_fn: UpdateFile,
) -> FileResponse:
    project_file = await projects_use_cases.rename_file(
        project=project,
        file_id=file_id,
        name=payload.name,
        get_file_fn=get_file_fn,
        find_entry_fn=find_entry_fn,
        update_file_fn=update_file_fn,
    )
    return mapper.domain_to_file_response(project_file)


@router.post("/{project_id}/files/{file_id}/move", response_model=FileResponse)
async def move_file_route(
    file_id: UUID,
    payload: MoveFileRequest,
    project: WritableProject,
    get_file_fn: GetFile,
    get_folder_fn: GetFolder,
    find_entry_fn: FindEntry,
    update_file_fn: UpdateFile,
) -> FileResponse:
    project_file = await projects_use_cases.move_file(
        project=project,
        file_id=file_id,
        folder_id=payload.folder_id,
        get_file_fn=get_file_fn,
        get_folder_fn=get_folder_fn,
        find_entry_fn=find_entry_fn,
        update_file_fn=update_file_fn,
    )
    return mapper.domain_to_file_response(project_file)


@router.delete("/{project_id}/files/{file_id}", response_model=DeleteResponse)
async def delete_file_route(
    file_id: UUID,
    project: WritableProject,
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
