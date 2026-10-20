from uuid import UUID

from src.core.bucket.ports import BucketStore
from src.core.exceptions import ValidationError
from src.projects.domain import Folder, FolderCreate, Project, ProjectContents
from src.projects.ports import (
    CreateFolderFn,
    DeleteFolderFn,
    FindEntryFn,
    GetFolderFn,
    ListContentsFn,
    ListFolderAncestorIdsFn,
    ListSubtreeFileIdsFn,
    ListTreeFn,
    UpdateFolderFn,
)

from .common import (
    assert_name_free,
    delete_objects,
    folder_not_found,
    require_folder,
    validate_name,
)


async def list_contents(
    project: Project,
    folder_id: UUID | None,
    get_folder_fn: GetFolderFn,
    list_contents_fn: ListContentsFn,
) -> ProjectContents:
    await require_folder(project, folder_id, get_folder_fn)
    return await list_contents_fn(project.id, folder_id)


async def get_tree(project: Project, list_tree_fn: ListTreeFn) -> ProjectContents:
    return await list_tree_fn(project.id)


async def create_folder(
    project: Project,
    name: str,
    parent_id: UUID | None,
    get_folder_fn: GetFolderFn,
    find_entry_fn: FindEntryFn,
    create_folder_fn: CreateFolderFn,
) -> Folder:
    cleaned = validate_name(name)
    await require_folder(project, parent_id, get_folder_fn)
    await assert_name_free(project.id, parent_id, cleaned, find_entry_fn)

    return await create_folder_fn(
        FolderCreate(project_id=project.id, parent_id=parent_id, name=cleaned)
    )


async def rename_folder(
    project: Project,
    folder_id: UUID,
    name: str,
    get_folder_fn: GetFolderFn,
    find_entry_fn: FindEntryFn,
    update_folder_fn: UpdateFolderFn,
) -> Folder:
    cleaned = validate_name(name)
    folder = await get_folder_fn(folder_id, project.id)
    if folder is None:
        raise folder_not_found()

    await assert_name_free(project.id, folder.parent_id, cleaned, find_entry_fn, folder.id)

    updated = await update_folder_fn(folder.id, {"name": cleaned})
    if updated is None:
        raise folder_not_found()
    return updated


async def move_folder(
    project: Project,
    folder_id: UUID,
    parent_id: UUID | None,
    get_folder_fn: GetFolderFn,
    list_folder_ancestor_ids_fn: ListFolderAncestorIdsFn,
    find_entry_fn: FindEntryFn,
    update_folder_fn: UpdateFolderFn,
) -> Folder:
    folder = await get_folder_fn(folder_id, project.id)
    if folder is None:
        raise folder_not_found()

    if parent_id is not None:
        await require_folder(project, parent_id, get_folder_fn)
        if folder.id in await list_folder_ancestor_ids_fn(parent_id):
            raise ValidationError(
                message="A folder cannot be moved into itself or one of its subfolders",
                code="folder_move_into_self",
            )

    await assert_name_free(project.id, parent_id, folder.name, find_entry_fn, folder.id)

    updated = await update_folder_fn(folder.id, {"parent_id": parent_id})
    if updated is None:
        raise folder_not_found()
    return updated


async def delete_folder(
    project: Project,
    folder_id: UUID,
    get_folder_fn: GetFolderFn,
    list_subtree_file_ids_fn: ListSubtreeFileIdsFn,
    delete_folder_fn: DeleteFolderFn,
    bucket_store: BucketStore,
) -> None:
    folder = await get_folder_fn(folder_id, project.id)
    if folder is None:
        raise folder_not_found()

    file_ids = await list_subtree_file_ids_fn(folder.id)

    if not await delete_folder_fn(folder.id):
        raise folder_not_found()

    await delete_objects(project.organization_id, file_ids, bucket_store)
