"""What the project, folder and file use cases share: the errors they raise, name rules,
the lookups that refuse a missing entry, and removing objects from the bucket."""

from collections.abc import Iterable
from uuid import UUID

from src.core.bucket.domain import BucketError
from src.core.bucket.ports import BucketStore
from src.core.exceptions import (
    ConflictError,
    InternalServerError,
    NotFoundError,
    ValidationError,
)
from src.projects import config, keys
from src.projects.domain import Folder, Project, ProjectFile
from src.projects.ports import FindEntryFn, GetFileFn, GetFolderFn


def project_not_found() -> NotFoundError:
    return NotFoundError(message="Project not found", code="project_not_found")


def folder_not_found() -> NotFoundError:
    return NotFoundError(message="Folder not found", code="folder_not_found")


def file_not_found() -> NotFoundError:
    return NotFoundError(message="File not found", code="file_not_found")


def unavailable() -> InternalServerError:
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


async def assert_name_free(
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


async def require_folder(
    project: Project, folder_id: UUID | None, get_folder_fn: GetFolderFn
) -> Folder | None:
    if folder_id is None:
        return None

    folder = await get_folder_fn(folder_id, project.id)
    if folder is None:
        raise folder_not_found()
    return folder


async def require_file(
    project: Project, file_id: UUID, get_file_fn: GetFileFn
) -> ProjectFile:
    project_file = await get_file_fn(file_id, project.id)
    if project_file is None:
        raise file_not_found()
    return project_file


async def delete_objects(
    organization_id: UUID, file_ids: Iterable[UUID], bucket_store: BucketStore
) -> None:
    # Runs after the rows are gone; a failure rolls them back, and deleting an
    # object that is already missing succeeds, so the caller can simply retry.
    try:
        for file_id in file_ids:
            await bucket_store.delete(keys.file_key(organization_id, file_id))
    except BucketError as exc:
        raise unavailable() from exc
