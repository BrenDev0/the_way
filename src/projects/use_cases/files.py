from uuid import UUID

from src.core.bucket.domain import BucketError
from src.core.bucket.ports import BucketStore
from src.core.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from src.projects import config, keys, links
from src.projects.domain import FileStatus, Project, ProjectFile, ProjectFileCreate
from src.projects.ports import (
    CreateFileFn,
    DeleteFileFn,
    FindEntryFn,
    GetFileFn,
    GetFileWithProjectFn,
    GetFolderFn,
    UpdateFileFn,
)

from .common import (
    assert_name_free,
    delete_objects,
    file_not_found,
    require_file,
    require_folder,
    unavailable,
    validate_name,
)

GIGABYTE = 1024 * 1024 * 1024


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
    await require_folder(project, folder_id, get_folder_fn)

    existing = await find_entry_fn(project.id, folder_id, cleaned)
    if isinstance(existing, ProjectFile) and existing.status is FileStatus.PENDING:
        # An upload that was never completed; the new one takes its place.
        await delete_file_fn(existing.id)
        await delete_objects(project.organization_id, [existing.id], bucket_store)
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
        raise unavailable() from exc

    return project_file, upload_url


async def complete_upload(
    project: Project,
    file_id: UUID,
    get_file_fn: GetFileFn,
    update_file_fn: UpdateFileFn,
    bucket_store: BucketStore,
) -> ProjectFile:
    project_file = await require_file(project, file_id, get_file_fn)
    key = keys.file_key(project.organization_id, project_file.id)

    try:
        stored = [obj for obj in await bucket_store.list(key) if obj.key == key]
    except BucketError as exc:
        raise unavailable() from exc

    if not stored:
        raise ConflictError(
            message="No file has been uploaded yet",
            code="file_not_uploaded",
        )

    updated = await update_file_fn(
        project_file.id, {"status": FileStatus.READY, "size_bytes": stored[0].size}
    )
    if updated is None:
        raise file_not_found()
    return updated


async def request_download(
    project: Project,
    file_id: UUID,
    get_file_fn: GetFileFn,
    bucket_store: BucketStore,
) -> tuple[ProjectFile, str]:
    project_file = await require_file(project, file_id, get_file_fn)

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
        raise unavailable() from exc

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
    from src.projects import paths  # paths builds on these use cases

    project_file = await require_file(project, file_id, get_file_fn)
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
    project_file = await require_file(project, file_id, get_file_fn)

    await assert_name_free(
        project.id, project_file.folder_id, cleaned, find_entry_fn, project_file.id
    )

    updated = await update_file_fn(project_file.id, {"name": cleaned})
    if updated is None:
        raise file_not_found()
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
    project_file = await require_file(project, file_id, get_file_fn)
    await require_folder(project, folder_id, get_folder_fn)

    await assert_name_free(
        project.id, folder_id, project_file.name, find_entry_fn, project_file.id
    )

    updated = await update_file_fn(project_file.id, {"folder_id": folder_id})
    if updated is None:
        raise file_not_found()
    return updated


async def delete_file(
    project: Project,
    file_id: UUID,
    get_file_fn: GetFileFn,
    delete_file_fn: DeleteFileFn,
    bucket_store: BucketStore,
) -> None:
    project_file = await require_file(project, file_id, get_file_fn)

    if not await delete_file_fn(project_file.id):
        raise file_not_found()

    await delete_objects(project.organization_id, [project_file.id], bucket_store)


async def request_image_url(
    file_id: UUID,
    signature: str,
    get_file_with_project_fn: GetFileWithProjectFn,
    bucket_store: BucketStore,
) -> str:
    """A fresh bucket URL for an image named by its signed link (links.py).

    The signature in the link is the whole of the permission, so anything wrong with it --
    a bad signature, no such file, a file not finished uploading, one that is not an image --
    is the same not-found: whether a file exists is not told to someone who cannot prove
    they may see it."""
    not_found = NotFoundError(message="Image not found", code="image_not_found")

    if not links.verify(file_id, signature):
        raise not_found

    found = await get_file_with_project_fn(file_id)
    if found is None:
        raise not_found
    project_file, project = found
    if project_file.status is not FileStatus.READY or not project_file.content_type.startswith(
        "image/"
    ):
        raise not_found

    try:
        return await bucket_store.presign_get(
            keys.file_key(project.organization_id, project_file.id), config.IMAGE_URL_TTL_SECONDS
        )
    except BucketError as exc:
        raise ServiceUnavailableError(
            "Images are unavailable right now", "image_unavailable"
        ) from exc
