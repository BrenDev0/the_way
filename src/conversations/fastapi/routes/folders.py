"""A person's own folders for their chats. Only theirs: nobody else's are ever seen or found."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from src.conversations.fastapi import dependencies as conversations_dependencies
from src.conversations.fastapi.dependencies import CurrentUser
from src.conversations.fastapi.schemas import FolderNameRequest, FolderResponse
from src.conversations.ports import (
    CountFoldersFn,
    CreateFolderFn,
    DeleteFolderFn,
    FindFolderByNameFn,
    ListFoldersFn,
    RenameFolderFn,
)
from src.conversations.use_cases import folders as folder_use_cases

router = APIRouter(tags=["conversations"])


@router.get("", response_model=list[FolderResponse])
async def list_folders_route(
    current_user: CurrentUser,
    list_folders_fn: Annotated[ListFoldersFn, Depends(conversations_dependencies.provide_list_folders_fn)],
) -> list[FolderResponse]:
    folders = await folder_use_cases.list_folders(current_user.id, list_folders_fn)
    return [FolderResponse.from_domain(folder) for folder in folders]


@router.post("", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
async def create_folder_route(
    payload: FolderNameRequest,
    current_user: CurrentUser,
    count_folders_fn: Annotated[CountFoldersFn, Depends(conversations_dependencies.provide_count_folders_fn)],
    find_folder_by_name_fn: Annotated[
        FindFolderByNameFn, Depends(conversations_dependencies.provide_find_folder_by_name_fn)
    ],
    create_folder_fn: Annotated[CreateFolderFn, Depends(conversations_dependencies.provide_create_folder_fn)],
) -> FolderResponse:
    folder = await folder_use_cases.create_folder(
        user_id=current_user.id,
        name=payload.name,
        count_folders_fn=count_folders_fn,
        find_folder_by_name_fn=find_folder_by_name_fn,
        create_folder_fn=create_folder_fn,
    )
    return FolderResponse.from_domain(folder)


@router.patch("/{folder_id}", response_model=FolderResponse)
async def rename_folder_route(
    folder_id: UUID,
    payload: FolderNameRequest,
    current_user: CurrentUser,
    find_folder_by_name_fn: Annotated[
        FindFolderByNameFn, Depends(conversations_dependencies.provide_find_folder_by_name_fn)
    ],
    rename_folder_fn: Annotated[RenameFolderFn, Depends(conversations_dependencies.provide_rename_folder_fn)],
) -> FolderResponse:
    folder = await folder_use_cases.rename_folder(
        folder_id=folder_id,
        user_id=current_user.id,
        name=payload.name,
        find_folder_by_name_fn=find_folder_by_name_fn,
        rename_folder_fn=rename_folder_fn,
    )
    return FolderResponse.from_domain(folder)


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder_route(
    folder_id: UUID,
    current_user: CurrentUser,
    delete_folder_fn: Annotated[DeleteFolderFn, Depends(conversations_dependencies.provide_delete_folder_fn)],
) -> None:
    """Its chats are not deleted: they go back to the main list."""
    await folder_use_cases.delete_folder(folder_id, current_user.id, delete_folder_fn)
