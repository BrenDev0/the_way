"""A project's contents and its folders."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from src.projects.fastapi.dependencies import (
    Bucket,
    CreateFolder,
    DeleteFolder,
    FindEntry,
    GetFolder,
    ListContents,
    ListFolderAncestorIds,
    ListSubtreeFileIds,
    ListTree,
    ReadableProject,
    UpdateFolder,
    WritableProject,
)
from src.projects.fastapi.schemas import (
    CreateFolderRequest,
    DeleteResponse,
    FolderResponse,
    MoveFolderRequest,
    ProjectContentsResponse,
    RenameRequest,
)
from src.projects.use_cases import folders as folder_use_cases

router = APIRouter(tags=["projects"])


@router.get("/{project_id}/contents", response_model=ProjectContentsResponse)
async def list_contents_route(
    project: ReadableProject,
    get_folder_fn: GetFolder,
    list_contents_fn: ListContents,
    folder_id: Annotated[UUID | None, Query(alias="folderId")] = None,
) -> ProjectContentsResponse:
    contents = await folder_use_cases.list_contents(
        project=project,
        folder_id=folder_id,
        get_folder_fn=get_folder_fn,
        list_contents_fn=list_contents_fn,
    )
    return ProjectContentsResponse.from_domain(contents)


@router.get("/{project_id}/tree", response_model=ProjectContentsResponse)
async def get_tree_route(project: ReadableProject, list_tree_fn: ListTree) -> ProjectContentsResponse:
    tree = await folder_use_cases.get_tree(project=project, list_tree_fn=list_tree_fn)
    return ProjectContentsResponse.from_domain(tree)


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
    folder = await folder_use_cases.create_folder(
        project=project,
        name=payload.name,
        parent_id=payload.parent_id,
        get_folder_fn=get_folder_fn,
        find_entry_fn=find_entry_fn,
        create_folder_fn=create_folder_fn,
    )
    return FolderResponse.from_domain(folder)


@router.patch("/{project_id}/folders/{folder_id}", response_model=FolderResponse)
async def rename_folder_route(
    folder_id: UUID,
    payload: RenameRequest,
    project: WritableProject,
    get_folder_fn: GetFolder,
    find_entry_fn: FindEntry,
    update_folder_fn: UpdateFolder,
) -> FolderResponse:
    folder = await folder_use_cases.rename_folder(
        project=project,
        folder_id=folder_id,
        name=payload.name,
        get_folder_fn=get_folder_fn,
        find_entry_fn=find_entry_fn,
        update_folder_fn=update_folder_fn,
    )
    return FolderResponse.from_domain(folder)


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
    folder = await folder_use_cases.move_folder(
        project=project,
        folder_id=folder_id,
        parent_id=payload.parent_id,
        get_folder_fn=get_folder_fn,
        list_folder_ancestor_ids_fn=list_folder_ancestor_ids_fn,
        find_entry_fn=find_entry_fn,
        update_folder_fn=update_folder_fn,
    )
    return FolderResponse.from_domain(folder)


@router.delete("/{project_id}/folders/{folder_id}", response_model=DeleteResponse)
async def delete_folder_route(
    folder_id: UUID,
    project: WritableProject,
    bucket_store: Bucket,
    get_folder_fn: GetFolder,
    list_subtree_file_ids_fn: ListSubtreeFileIds,
    delete_folder_fn: DeleteFolder,
) -> DeleteResponse:
    await folder_use_cases.delete_folder(
        project=project,
        folder_id=folder_id,
        get_folder_fn=get_folder_fn,
        list_subtree_file_ids_fn=list_subtree_file_ids_fn,
        delete_folder_fn=delete_folder_fn,
        bucket_store=bucket_store,
    )
    return DeleteResponse(detail="Folder deleted")
