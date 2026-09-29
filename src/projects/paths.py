"""Paths inside a project, for the agent's file tools.

The desktop app works with ids; the model works with paths, the way it was taught to by
every file system it has seen. This module is the translation: 'docs/reports/q3.md' is
walked one folder at a time through the same case-insensitive lookup the routes use, so
a path and an id always mean the same entry.
"""

import tempfile
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from src.core.bucket.domain import BucketError
from src.core.bucket.ports import BucketStore
from src.core.exceptions import (
    ConflictError,
    InternalServerError,
    NotFoundError,
    ValidationError,
)

from . import keys, use_cases
from .domain import (
    FileStatus,
    Folder,
    FolderCreate,
    Project,
    ProjectContents,
    ProjectFile,
    ProjectFileCreate,
)
from .ports import (
    CreateFileFn,
    CreateFolderFn,
    FindEntryFn,
    ListContentsFn,
    ListTreeFn,
    UpdateFileFn,
)

Entry = Folder | ProjectFile


def split(path: str) -> list[str]:
    """The segments of a path. '.', '' and a leading or trailing slash all mean the
    project root; '..' is refused rather than resolved, since nothing sits above a root."""
    segments = [part for part in path.replace("\\", "/").split("/") if part not in ("", ".")]
    if ".." in segments:
        raise ValidationError(
            message=f"'{path}' climbs out of the project with '..'",
            code="project_path_invalid",
        )
    return [use_cases.validate_name(segment) for segment in segments]


def join(segments: Sequence[str]) -> str:
    return "/".join(segments) or "."


async def resolve(
    project: Project, segments: Sequence[str], find_entry_fn: FindEntryFn
) -> Entry | None:
    """The entry at a path, or None for the root. Raises when any segment is missing or a
    file sits where a folder is needed."""
    folder_id: UUID | None = None
    entry: Entry | None = None

    for depth, segment in enumerate(segments):
        entry = await find_entry_fn(project.id, folder_id, segment)
        if entry is None:
            raise NotFoundError(
                message=f"Nothing named '{join(segments[: depth + 1])}' in {project.name}",
                code="project_path_not_found",
            )
        if depth < len(segments) - 1:
            if not isinstance(entry, Folder):
                raise ValidationError(
                    message=f"'{join(segments[: depth + 1])}' is a file, not a folder",
                    code="project_path_not_a_folder",
                )
            folder_id = entry.id

    return entry


async def resolve_folder(
    project: Project, segments: Sequence[str], find_entry_fn: FindEntryFn
) -> UUID | None:
    entry = await resolve(project, segments, find_entry_fn)
    if entry is None:
        return None
    if not isinstance(entry, Folder):
        raise ValidationError(
            message=f"'{join(segments)}' is a file, not a folder",
            code="project_path_not_a_folder",
        )
    return entry.id


async def ensure_folder(
    project: Project,
    segments: Sequence[str],
    find_entry_fn: FindEntryFn,
    create_folder_fn: CreateFolderFn,
) -> UUID | None:
    """The folder at a path, creating whatever is missing -- mkdir -p."""
    folder_id: UUID | None = None

    for depth, segment in enumerate(segments):
        entry = await find_entry_fn(project.id, folder_id, segment)
        if entry is None:
            entry = await create_folder_fn(
                FolderCreate(project_id=project.id, parent_id=folder_id, name=segment)
            )
        elif not isinstance(entry, Folder):
            raise ConflictError(
                message=f"'{join(segments[: depth + 1])}' is a file, so no folder can go there",
                code="project_path_not_a_folder",
            )
        folder_id = entry.id

    return folder_id


async def list_paths(project: Project, list_tree_fn: ListTreeFn) -> list[tuple[str, Entry]]:
    """Every entry with its full path, folders first at each level."""
    tree: ProjectContents = await list_tree_fn(project.id)
    folders = {folder.id: folder for folder in tree.folders}

    def path_of(parent_id: UUID | None, name: str) -> str:
        parts = [name]
        while parent_id is not None:
            parent = folders[parent_id]
            parts.append(parent.name)
            parent_id = parent.parent_id
        return "/".join(reversed(parts))

    entries: list[tuple[str, Entry]] = [
        (path_of(folder.parent_id, folder.name), folder) for folder in tree.folders
    ]
    entries += [(path_of(f.folder_id, f.name), f) for f in tree.files]
    return sorted(entries, key=lambda item: (not isinstance(item[1], Folder), item[0].lower()))


async def store_file(
    project: Project,
    folder_id: UUID | None,
    name: str,
    content: bytes,
    content_type: str,
    uploaded_by: UUID,
    overwrite: bool,
    find_entry_fn: FindEntryFn,
    create_file_fn: CreateFileFn,
    update_file_fn: UpdateFileFn,
    bucket_store: BucketStore,
) -> ProjectFile:
    """Write bytes as a finished file in one step -- the server holds them already, so
    there is no presigned upload to wait for."""
    existing = await find_entry_fn(project.id, folder_id, name)

    if isinstance(existing, Folder):
        raise ConflictError(
            message=f"'{existing.name}' is a folder, so no file can be written there",
            code="project_entry_name_taken",
        )
    if existing is not None and existing.status is FileStatus.READY and not overwrite:
        raise ConflictError(
            message=f"'{existing.name}' already exists. Pass overwrite=true to replace it.",
            code="project_entry_name_taken",
        )

    project_file = existing or await create_file_fn(
        ProjectFileCreate(
            project_id=project.id,
            folder_id=folder_id,
            name=name,
            content_type=content_type,
            size_bytes=len(content),
            uploaded_by=uploaded_by,
        )
    )

    with tempfile.TemporaryDirectory() as workspace:
        source = Path(workspace) / "upload"
        source.write_bytes(content)
        try:
            await bucket_store.put(keys.file_key(project.organization_id, project_file.id), source)
        except BucketError as exc:
            raise _unavailable() from exc

    updated = await update_file_fn(
        project_file.id, {"status": FileStatus.READY, "size_bytes": len(content)}
    )
    if updated is None:
        raise NotFoundError(message="File not found", code="file_not_found")
    return updated


async def load_file(
    project: Project, project_file: ProjectFile, bucket_store: BucketStore
) -> bytes:
    if project_file.status is not FileStatus.READY:
        raise ConflictError(
            message=f"'{project_file.name}' has not finished uploading",
            code="file_not_uploaded",
        )

    with tempfile.TemporaryDirectory() as workspace:
        destination = Path(workspace) / "download"
        try:
            await bucket_store.get(
                keys.file_key(project.organization_id, project_file.id), destination
            )
        except BucketError as exc:
            raise _unavailable() from exc
        return destination.read_bytes() if destination.exists() else b""


async def copy_entry(
    source_project: Project,
    entry: Entry,
    target_project: Project,
    target_folder_id: UUID | None,
    name: str,
    uploaded_by: UUID,
    find_entry_fn: FindEntryFn,
    create_folder_fn: CreateFolderFn,
    create_file_fn: CreateFileFn,
    update_file_fn: UpdateFileFn,
    list_contents_fn: ListContentsFn,
    bucket_store: BucketStore,
) -> int:
    """Copy a file, or a folder and everything under it, returning the number of files.
    Objects are copied inside the bucket; the bytes never pass through the worker."""
    if isinstance(entry, ProjectFile):
        if entry.status is not FileStatus.READY:
            return 0
        if await find_entry_fn(target_project.id, target_folder_id, name) is not None:
            raise ConflictError(
                message=f"Something named '{name}' is already in the destination",
                code="project_entry_name_taken",
            )
        copied = await create_file_fn(
            ProjectFileCreate(
                project_id=target_project.id,
                folder_id=target_folder_id,
                name=name,
                content_type=entry.content_type,
                size_bytes=entry.size_bytes,
                uploaded_by=uploaded_by,
            )
        )
        try:
            await bucket_store.copy(
                keys.file_key(source_project.organization_id, entry.id),
                keys.file_key(target_project.organization_id, copied.id),
            )
        except BucketError as exc:
            raise _unavailable() from exc
        await update_file_fn(copied.id, {"status": FileStatus.READY})
        return 1

    existing = await find_entry_fn(target_project.id, target_folder_id, name)
    if existing is None:
        created = await create_folder_fn(
            FolderCreate(project_id=target_project.id, parent_id=target_folder_id, name=name)
        )
        folder_id = created.id
    elif isinstance(existing, Folder):
        folder_id = existing.id
    else:
        raise ConflictError(
            message=f"'{name}' in the destination is a file, not a folder",
            code="project_entry_name_taken",
        )

    contents = await list_contents_fn(source_project.id, entry.id)
    total = 0
    children: list[Entry] = [*contents.folders, *contents.files]
    for child in children:
        total += await copy_entry(
            source_project,
            child,
            target_project,
            folder_id,
            child.name,
            uploaded_by,
            find_entry_fn,
            create_folder_fn,
            create_file_fn,
            update_file_fn,
            list_contents_fn,
            bucket_store,
        )
    return total


def _unavailable() -> InternalServerError:
    return InternalServerError(
        message="Unable to process request at this time",
        code="project_storage_unavailable",
    )
