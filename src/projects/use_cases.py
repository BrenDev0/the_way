from collections.abc import Iterable, Sequence
from uuid import UUID

from src.core.bucket.domain import BucketError
from src.core.bucket.ports import BucketStore
from src.core.exceptions import (
    AuthorizationError,
    ConflictError,
    InternalServerError,
    NotFoundError,
    ValidationError,
)
from src.users.domain import Role, User

from . import config, keys
from .domain import (
    FileStatus,
    Folder,
    FolderCreate,
    Project,
    ProjectContents,
    ProjectCreate,
    ProjectFile,
    ProjectFileCreate,
)
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

GIGABYTE = 1024 * 1024 * 1024


def _project_not_found() -> NotFoundError:
    return NotFoundError(message="Project not found", code="project_not_found")


def _folder_not_found() -> NotFoundError:
    return NotFoundError(message="Folder not found", code="folder_not_found")


def _file_not_found() -> NotFoundError:
    return NotFoundError(message="File not found", code="file_not_found")


def _unavailable() -> InternalServerError:
    return InternalServerError(
        message="Unable to process request at this time",
        code="project_storage_unavailable",
    )


def validate_name(name: str) -> str:
    cleaned = name.strip()

    if not cleaned or len(cleaned) > config.MAX_NAME_CHARS:
        raise ValidationError(
            message=f"A name must be 1 to {config.MAX_NAME_CHARS} characters",
            code="project_name_invalid",
        )

    if cleaned in {".", ".."} or cleaned.endswith("."):
        raise ValidationError(
            message="A name cannot be '.', '..' or end with a dot",
            code="project_name_invalid",
        )

    if any(char in config.INVALID_NAME_CHARS or ord(char) < 32 for char in cleaned):
        raise ValidationError(
            message='A name cannot contain any of < > : " / \\ | ? *',
            code="project_name_invalid",
        )

    if cleaned.split(".")[0].lower() in config.RESERVED_NAMES:
        raise ValidationError(
            message=f"'{cleaned}' is a reserved name on Windows",
            code="project_name_invalid",
        )

    return cleaned


async def _assert_name_free(
    project_id: UUID,
    folder_id: UUID | None,
    name: str,
    find_entry_fn: FindEntryFn,
    ignore_id: UUID | None = None,
) -> None:
    existing = await find_entry_fn(project_id, folder_id, name)
    if existing is not None and existing.id != ignore_id:
        raise ConflictError(
            message=f"Something named '{existing.name}' already exists in this folder",
            code="project_entry_name_taken",
        )


async def _require_folder(
    project: Project, folder_id: UUID | None, get_folder_fn: GetFolderFn
) -> Folder | None:
    if folder_id is None:
        return None

    folder = await get_folder_fn(folder_id, project.id)
    if folder is None:
        raise _folder_not_found()
    return folder


async def _require_file(
    project: Project, file_id: UUID, get_file_fn: GetFileFn
) -> ProjectFile:
    project_file = await get_file_fn(file_id, project.id)
    if project_file is None:
        raise _file_not_found()
    return project_file


async def _delete_objects(
    organization_id: UUID, file_ids: Iterable[UUID], bucket_store: BucketStore
) -> None:
    # Runs after the rows are gone; a failure rolls them back, and deleting an
    # object that is already missing succeeds, so the caller can simply retry.
    try:
        for file_id in file_ids:
            await bucket_store.delete(keys.file_key(organization_id, file_id))
    except BucketError as exc:
        raise _unavailable() from exc


async def resolve_owned_project(
    project_id: UUID, user: User, get_project_fn: GetProjectFn
) -> Project:
    """A project of the user's own -- for renaming or deleting it. The library is
    nobody's, so it can be neither."""
    project = await get_project_fn(project_id, user.organization_id)
    if project is None or project.owner_id != user.id:
        raise _project_not_found()
    return project


LIBRARY_EDITORS = frozenset({Role.OWNER, Role.ADMIN})


async def resolve_readable_project(
    project_id: UUID, user: User, get_project_fn: GetProjectFn
) -> Project:
    """The user's own project, or their organization's library, which every member
    reads."""
    project = await get_project_fn(project_id, user.organization_id)
    if project is None or not (project.owner_id == user.id or project.shared):
        raise _project_not_found()
    return project


async def resolve_writable_project(
    project_id: UUID, user: User, get_project_fn: GetProjectFn
) -> Project:
    """Where the user may add, change or remove files and folders: their own projects,
    and the library when they are an owner or admin."""
    project = await resolve_readable_project(project_id, user, get_project_fn)
    if project.shared and user.role not in LIBRARY_EDITORS:
        raise AuthorizationError(
            message="Only owners and admins can change the organization's library",
            code="library_read_only",
        )
    return project


def _not_reserved(name: str) -> str:
    if name.lower() == config.LIBRARY_PROJECT.lower():
        raise ConflictError(
            message=f"'{config.LIBRARY_PROJECT}' is the organization's shared library; pick another name",
            code="project_name_reserved",
        )
    return name


async def create_project(
    owner: User,
    name: str,
    list_projects_for_owner_fn: ListProjectsForOwnerFn,
    create_project_fn: CreateProjectFn,
) -> Project:
    cleaned = _not_reserved(validate_name(name))

    held = await list_projects_for_owner_fn(owner.id)
    if any(project.name.lower() == cleaned.lower() for project in held):
        raise ConflictError(
            message="A project with that name already exists",
            code="project_name_taken",
        )

    return await create_project_fn(
        ProjectCreate(organization_id=owner.organization_id, owner_id=owner.id, name=cleaned)
    )


async def list_projects(
    owner_id: UUID, list_projects_for_owner_fn: ListProjectsForOwnerFn
) -> Sequence[Project]:
    return await list_projects_for_owner_fn(owner_id)


async def rename_project(
    project: Project, name: str, update_project_fn: UpdateProjectFn
) -> Project:
    updated = await update_project_fn(project.id, {"name": _not_reserved(validate_name(name))})
    if updated is None:
        raise _project_not_found()
    return updated


async def delete_project(
    project: Project,
    list_project_file_ids_fn: ListProjectFileIdsFn,
    delete_project_fn: DeleteProjectFn,
    bucket_store: BucketStore,
) -> None:
    file_ids = await list_project_file_ids_fn(project.id)

    if not await delete_project_fn(project.id):
        raise _project_not_found()

    await _delete_objects(project.organization_id, file_ids, bucket_store)


async def list_contents(
    project: Project,
    folder_id: UUID | None,
    get_folder_fn: GetFolderFn,
    list_contents_fn: ListContentsFn,
) -> ProjectContents:
    await _require_folder(project, folder_id, get_folder_fn)
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
    await _require_folder(project, parent_id, get_folder_fn)
    await _assert_name_free(project.id, parent_id, cleaned, find_entry_fn)

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
        raise _folder_not_found()

    await _assert_name_free(project.id, folder.parent_id, cleaned, find_entry_fn, folder.id)

    updated = await update_folder_fn(folder.id, {"name": cleaned})
    if updated is None:
        raise _folder_not_found()
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
        raise _folder_not_found()

    if parent_id is not None:
        await _require_folder(project, parent_id, get_folder_fn)
        if folder.id in await list_folder_ancestor_ids_fn(parent_id):
            raise ValidationError(
                message="A folder cannot be moved into itself or one of its subfolders",
                code="folder_move_into_self",
            )

    await _assert_name_free(project.id, parent_id, folder.name, find_entry_fn, folder.id)

    updated = await update_folder_fn(folder.id, {"parent_id": parent_id})
    if updated is None:
        raise _folder_not_found()
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
        raise _folder_not_found()

    file_ids = await list_subtree_file_ids_fn(folder.id)

    if not await delete_folder_fn(folder.id):
        raise _folder_not_found()

    await _delete_objects(project.organization_id, file_ids, bucket_store)


async def request_upload(
    project: Project,
    name: str,
    folder_id: UUID | None,
    content_type: str,
    size_bytes: int,
    uploaded_by: UUID,
    get_folder_fn: GetFolderFn,
    find_entry_fn: FindEntryFn,
    delete_file_fn: DeleteFileFn,
    create_file_fn: CreateFileFn,
    bucket_store: BucketStore,
) -> tuple[ProjectFile, str]:
    if size_bytes > config.MAX_FILE_BYTES:
        raise ValidationError(
            message=f"That file is larger than the {config.MAX_FILE_BYTES // GIGABYTE} GB limit",
            code="file_too_large",
        )

    cleaned = validate_name(name)
    await _require_folder(project, folder_id, get_folder_fn)

    existing = await find_entry_fn(project.id, folder_id, cleaned)
    if isinstance(existing, ProjectFile) and existing.status is FileStatus.PENDING:
        # An upload that was never completed; the new one takes its place.
        await delete_file_fn(existing.id)
        await _delete_objects(project.organization_id, [existing.id], bucket_store)
    elif existing is not None:
        raise ConflictError(
            message=f"Something named '{existing.name}' already exists in this folder",
            code="project_entry_name_taken",
        )

    project_file = await create_file_fn(
        ProjectFileCreate(
            project_id=project.id,
            folder_id=folder_id,
            name=cleaned,
            content_type=content_type,
            size_bytes=size_bytes,
            uploaded_by=uploaded_by,
        )
    )

    try:
        upload_url = await bucket_store.presign_put(
            keys.file_key(project.organization_id, project_file.id),
            content_type,
            config.UPLOAD_URL_TTL_SECONDS,
        )
    except BucketError as exc:
        raise _unavailable() from exc

    return project_file, upload_url


async def complete_upload(
    project: Project,
    file_id: UUID,
    get_file_fn: GetFileFn,
    update_file_fn: UpdateFileFn,
    bucket_store: BucketStore,
) -> ProjectFile:
    project_file = await _require_file(project, file_id, get_file_fn)
    key = keys.file_key(project.organization_id, project_file.id)

    try:
        stored = [obj for obj in await bucket_store.list(key) if obj.key == key]
    except BucketError as exc:
        raise _unavailable() from exc

    if not stored:
        raise ConflictError(
            message="No file has been uploaded yet",
            code="file_not_uploaded",
        )

    updated = await update_file_fn(
        project_file.id, {"status": FileStatus.READY, "size_bytes": stored[0].size}
    )
    if updated is None:
        raise _file_not_found()
    return updated


async def request_download(
    project: Project,
    file_id: UUID,
    get_file_fn: GetFileFn,
    bucket_store: BucketStore,
) -> tuple[ProjectFile, str]:
    project_file = await _require_file(project, file_id, get_file_fn)

    if project_file.status is not FileStatus.READY:
        raise ConflictError(
            message="That file has not finished uploading",
            code="file_not_uploaded",
        )

    try:
        download_url = await bucket_store.presign_get(
            keys.file_key(project.organization_id, project_file.id),
            config.DOWNLOAD_URL_TTL_SECONDS,
            project_file.name,
        )
    except BucketError as exc:
        raise _unavailable() from exc

    return project_file, download_url


async def read_file(
    project: Project,
    file_id: UUID,
    get_file_fn: GetFileFn,
    bucket_store: BucketStore,
) -> tuple[ProjectFile, bytes]:
    """A file's bytes, fetched by the server itself. A presigned URL is signed for the
    bucket's address as the server sees it -- inside Docker that is a hostname no desktop
    can resolve -- so a client that needs the file goes through here instead."""
    from . import paths  # paths builds on this module

    project_file = await _require_file(project, file_id, get_file_fn)
    if project_file.size_bytes > config.MAX_CONTENT_BYTES:
        raise ValidationError(
            message=f"'{project_file.name}' is too large to open here; download it instead",
            code="file_too_large_to_open",
        )
    return project_file, await paths.load_file(project, project_file, bucket_store)


async def rename_file(
    project: Project,
    file_id: UUID,
    name: str,
    get_file_fn: GetFileFn,
    find_entry_fn: FindEntryFn,
    update_file_fn: UpdateFileFn,
) -> ProjectFile:
    cleaned = validate_name(name)
    project_file = await _require_file(project, file_id, get_file_fn)

    await _assert_name_free(
        project.id, project_file.folder_id, cleaned, find_entry_fn, project_file.id
    )

    updated = await update_file_fn(project_file.id, {"name": cleaned})
    if updated is None:
        raise _file_not_found()
    return updated


async def move_file(
    project: Project,
    file_id: UUID,
    folder_id: UUID | None,
    get_file_fn: GetFileFn,
    get_folder_fn: GetFolderFn,
    find_entry_fn: FindEntryFn,
    update_file_fn: UpdateFileFn,
) -> ProjectFile:
    project_file = await _require_file(project, file_id, get_file_fn)
    await _require_folder(project, folder_id, get_folder_fn)

    await _assert_name_free(
        project.id, folder_id, project_file.name, find_entry_fn, project_file.id
    )

    updated = await update_file_fn(project_file.id, {"folder_id": folder_id})
    if updated is None:
        raise _file_not_found()
    return updated


async def delete_file(
    project: Project,
    file_id: UUID,
    get_file_fn: GetFileFn,
    delete_file_fn: DeleteFileFn,
    bucket_store: BucketStore,
) -> None:
    project_file = await _require_file(project, file_id, get_file_fn)

    if not await delete_file_fn(project_file.id):
        raise _file_not_found()

    await _delete_objects(project.organization_id, [project_file.id], bucket_store)
