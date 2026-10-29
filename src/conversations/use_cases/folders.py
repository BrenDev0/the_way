from collections.abc import Sequence
from uuid import UUID

from src.conversations.domain import Conversation, ConversationFolder
from src.conversations.ports import (
    CountFoldersFn,
    CreateFolderFn,
    DeleteFolderFn,
    FindFolderByNameFn,
    GetFolderFn,
    ListFoldersFn,
    MoveConversationFn,
    RenameFolderFn,
)
from src.core.exceptions import ConflictError, NotFoundError, ValidationError

from .common import not_found

MAX_FOLDERS_PER_USER = 50
MAX_NAME_LENGTH = 60


def folder_not_found() -> NotFoundError:
    return NotFoundError(message="Folder not found", code="conversation_folder_not_found")


def _clean(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValidationError(message="A folder needs a name", code="folder_name_required")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValidationError(
            message=f"A folder's name can have at most {MAX_NAME_LENGTH} characters",
            code="folder_name_too_long",
        )
    return cleaned


def _name_taken() -> ConflictError:
    return ConflictError(message="You already have a folder with that name", code="folder_name_taken")


async def list_folders(user_id: UUID, list_folders_fn: ListFoldersFn) -> Sequence[ConversationFolder]:
    return await list_folders_fn(user_id)


async def create_folder(
    user_id: UUID,
    name: str,
    count_folders_fn: CountFoldersFn,
    find_folder_by_name_fn: FindFolderByNameFn,
    create_folder_fn: CreateFolderFn,
) -> ConversationFolder:
    cleaned = _clean(name)
    if await find_folder_by_name_fn(user_id, cleaned) is not None:
        raise _name_taken()
    if await count_folders_fn(user_id) >= MAX_FOLDERS_PER_USER:
        raise ConflictError(
            message=f"You can have at most {MAX_FOLDERS_PER_USER} folders: delete one before making another",
            code="conversation_folder_limit_reached",
        )
    return await create_folder_fn(user_id, cleaned)


async def rename_folder(
    folder_id: UUID,
    user_id: UUID,
    name: str,
    find_folder_by_name_fn: FindFolderByNameFn,
    rename_folder_fn: RenameFolderFn,
) -> ConversationFolder:
    cleaned = _clean(name)
    same = await find_folder_by_name_fn(user_id, cleaned)
    if same is not None and same.id != folder_id:
        raise _name_taken()
    folder = await rename_folder_fn(folder_id, user_id, cleaned)
    if folder is None:
        raise folder_not_found()
    return folder


async def delete_folder(folder_id: UUID, user_id: UUID, delete_folder_fn: DeleteFolderFn) -> None:
    """Its chats are not deleted: they are back in the main list."""
    if not await delete_folder_fn(folder_id, user_id):
        raise folder_not_found()


async def move_conversation(
    conversation_id: UUID,
    user_id: UUID,
    folder_id: UUID | None,
    get_folder_fn: GetFolderFn,
    move_conversation_fn: MoveConversationFn,
) -> Conversation:
    """Files a chat in one of the person's folders, or (None) takes it out of its folder."""
    if folder_id is not None and await get_folder_fn(folder_id, user_id) is None:
        raise folder_not_found()
    conversation = await move_conversation_fn(conversation_id, user_id, folder_id)
    if conversation is None:
        raise not_found()
    return conversation
