from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConflictError, ValidationError
from src.projects.domain import (
    Folder,
    FolderCreate,
    Project,
    ProjectContents,
    ProjectCreate,
    ProjectFile,
    ProjectFileCreate,
)

from . import mapper
from .models import FileRow, FolderRow, ProjectRow

UPDATABLE_PROJECT_FIELDS = frozenset({"name", "owner_id"})
UPDATABLE_FOLDER_FIELDS = frozenset({"name", "parent_id"})
UPDATABLE_FILE_FIELDS = frozenset({"name", "folder_id", "status", "size_bytes"})


async def _flush(session: AsyncSession) -> None:
    # Two requests can pass the use-case name check at once; the unique
    # indexes are the final word.
    try:
        await session.flush()
    except IntegrityError as exc:
        if "uq_project_owner_name" in str(exc.orig):
            raise ConflictError(
                message="A project with that name already exists",
                code="project_name_taken",
            ) from exc
        if "uq_project_folder_parent_name" in str(exc.orig) or (
            "uq_project_file_folder_name" in str(exc.orig)
        ):
            raise ConflictError(
                message="Something with that name already exists in this folder",
                code="project_entry_name_taken",
            ) from exc
        raise


def _apply(row: Any, changes: dict[str, Any], allowed: frozenset[str], code: str) -> None:
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationError(
            message=f"Cannot update: {', '.join(sorted(unknown))}",
            code=code,
        )

    for field, value in changes.items():
        setattr(row, field, value)


async def create_project(session: AsyncSession, project: ProjectCreate) -> Project:
    row = mapper.project_create_to_row(project)
    session.add(row)
    await _flush(session)
    await session.refresh(row)
    return mapper.project_row_to_domain(row)


async def get_library(session: AsyncSession, organization_id: UUID) -> Project | None:
    result = await session.execute(
        select(ProjectRow).where(ProjectRow.organization_id == organization_id, ProjectRow.shared.is_(True))
    )
    row = result.scalar_one_or_none()
    return mapper.project_row_to_domain(row) if row else None


async def get_or_create_library(session: AsyncSession, organization_id: UUID, name: str) -> Project:
    """The organization's library, made the first time anyone asks for it. Two first
    requests at once meet the one-per-organization index; the loser reads the winner's."""
    found = await get_library(session, organization_id)
    if found is not None:
        return found
    row = ProjectRow(organization_id=organization_id, owner_id=None, name=name, shared=True)
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        found = await get_library(session, organization_id)
        if found is None:
            raise
        return found
    await session.refresh(row)
    return mapper.project_row_to_domain(row)


async def list_projects_for_owner(
    session: AsyncSession, owner_id: UUID
) -> Sequence[Project]:
    result = await session.execute(
        select(ProjectRow)
        .where(ProjectRow.owner_id == owner_id)
        .order_by(func.lower(ProjectRow.name))
    )
    return [mapper.project_row_to_domain(row) for row in result.scalars().all()]


async def list_projects_for_organization(
    session: AsyncSession,
    organization_id: UUID,
    owner_id: UUID | None = None,
) -> Sequence[Project]:
    # members' projects: the library is managed on its own (library routes), never
    # listed, reassigned or deleted here
    statement = select(ProjectRow).where(
        ProjectRow.organization_id == organization_id, ProjectRow.shared.is_(False)
    )
    if owner_id is not None:
        statement = statement.where(ProjectRow.owner_id == owner_id)

    result = await session.execute(statement.order_by(func.lower(ProjectRow.name)))
    return [mapper.project_row_to_domain(row) for row in result.scalars().all()]


async def get_project(
    session: AsyncSession, project_id: UUID, organization_id: UUID
) -> Project | None:
    result = await session.execute(
        select(ProjectRow).where(
            ProjectRow.id == project_id,
            ProjectRow.organization_id == organization_id,
        )
    )
    row = result.scalar_one_or_none()
    return mapper.project_row_to_domain(row) if row else None


async def update_project(
    session: AsyncSession, project_id: UUID, changes: dict[str, Any]
) -> Project | None:
    row = await session.get(ProjectRow, project_id)
    if row is None:
        return None

    _apply(row, changes, UPDATABLE_PROJECT_FIELDS, "project_field_not_updatable")
    await _flush(session)
    await session.refresh(row)
    return mapper.project_row_to_domain(row)


async def delete_project(session: AsyncSession, project_id: UUID) -> bool:
    result = await session.execute(
        delete(ProjectRow).where(ProjectRow.id == project_id).returning(ProjectRow.id)
    )
    return result.scalar_one_or_none() is not None


async def list_project_file_ids(session: AsyncSession, project_id: UUID) -> Sequence[UUID]:
    result = await session.execute(select(FileRow.id).where(FileRow.project_id == project_id))
    return list(result.scalars().all())


async def list_contents(
    session: AsyncSession, project_id: UUID, folder_id: UUID | None
) -> ProjectContents:
    folders = await session.execute(
        select(FolderRow)
        .where(
            FolderRow.project_id == project_id,
            FolderRow.parent_id.is_not_distinct_from(folder_id),
        )
        .order_by(func.lower(FolderRow.name))
    )
    files = await session.execute(
        select(FileRow)
        .where(
            FileRow.project_id == project_id,
            FileRow.folder_id.is_not_distinct_from(folder_id),
        )
        .order_by(func.lower(FileRow.name))
    )
    return ProjectContents(
        folders=[mapper.folder_row_to_domain(row) for row in folders.scalars().all()],
        files=[mapper.file_row_to_domain(row) for row in files.scalars().all()],
    )


async def list_tree(session: AsyncSession, project_id: UUID) -> ProjectContents:
    folders = await session.execute(
        select(FolderRow)
        .where(FolderRow.project_id == project_id)
        .order_by(func.lower(FolderRow.name))
    )
    files = await session.execute(
        select(FileRow)
        .where(FileRow.project_id == project_id)
        .order_by(func.lower(FileRow.name))
    )
    return ProjectContents(
        folders=[mapper.folder_row_to_domain(row) for row in folders.scalars().all()],
        files=[mapper.file_row_to_domain(row) for row in files.scalars().all()],
    )


async def find_entry(
    session: AsyncSession, project_id: UUID, folder_id: UUID | None, name: str
) -> Folder | ProjectFile | None:
    folder = await session.execute(
        select(FolderRow).where(
            FolderRow.project_id == project_id,
            FolderRow.parent_id.is_not_distinct_from(folder_id),
            func.lower(FolderRow.name) == name.lower(),
        )
    )
    folder_row = folder.scalar_one_or_none()
    if folder_row is not None:
        return mapper.folder_row_to_domain(folder_row)

    file = await session.execute(
        select(FileRow).where(
            FileRow.project_id == project_id,
            FileRow.folder_id.is_not_distinct_from(folder_id),
            func.lower(FileRow.name) == name.lower(),
        )
    )
    file_row = file.scalar_one_or_none()
    return mapper.file_row_to_domain(file_row) if file_row else None


async def create_folder(session: AsyncSession, folder: FolderCreate) -> Folder:
    row = mapper.folder_create_to_row(folder)
    session.add(row)
    await _flush(session)
    await session.refresh(row)
    return mapper.folder_row_to_domain(row)


async def get_folder(
    session: AsyncSession, folder_id: UUID, project_id: UUID
) -> Folder | None:
    result = await session.execute(
        select(FolderRow).where(FolderRow.id == folder_id, FolderRow.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    return mapper.folder_row_to_domain(row) if row else None


async def update_folder(
    session: AsyncSession, folder_id: UUID, changes: dict[str, Any]
) -> Folder | None:
    row = await session.get(FolderRow, folder_id)
    if row is None:
        return None

    _apply(row, changes, UPDATABLE_FOLDER_FIELDS, "folder_field_not_updatable")
    await _flush(session)
    await session.refresh(row)
    return mapper.folder_row_to_domain(row)


async def delete_folder(session: AsyncSession, folder_id: UUID) -> bool:
    result = await session.execute(
        delete(FolderRow).where(FolderRow.id == folder_id).returning(FolderRow.id)
    )
    return result.scalar_one_or_none() is not None


async def list_folder_ancestor_ids(session: AsyncSession, folder_id: UUID) -> Sequence[UUID]:
    """The folder itself and every folder above it."""
    chain = (
        select(FolderRow.id, FolderRow.parent_id)
        .where(FolderRow.id == folder_id)
        .cte("chain", recursive=True)
    )
    chain = chain.union_all(
        select(FolderRow.id, FolderRow.parent_id).join(chain, FolderRow.id == chain.c.parent_id)
    )
    result = await session.execute(select(chain.c.id))
    return list(result.scalars().all())


async def list_subtree_file_ids(session: AsyncSession, folder_id: UUID) -> Sequence[UUID]:
    """Every file in the folder or any folder below it."""
    subtree = select(FolderRow.id).where(FolderRow.id == folder_id).cte("subtree", recursive=True)
    subtree = subtree.union_all(
        select(FolderRow.id).join(subtree, FolderRow.parent_id == subtree.c.id)
    )
    result = await session.execute(
        select(FileRow.id).where(FileRow.folder_id.in_(select(subtree.c.id)))
    )
    return list(result.scalars().all())


async def create_file(session: AsyncSession, project_file: ProjectFileCreate) -> ProjectFile:
    row = mapper.file_create_to_row(project_file)
    session.add(row)
    await _flush(session)
    await session.refresh(row)
    return mapper.file_row_to_domain(row)


async def get_file(
    session: AsyncSession, file_id: UUID, project_id: UUID
) -> ProjectFile | None:
    result = await session.execute(
        select(FileRow).where(FileRow.id == file_id, FileRow.project_id == project_id)
    )
    row = result.scalar_one_or_none()
    return mapper.file_row_to_domain(row) if row else None


async def get_file_with_project(
    session: AsyncSession, file_id: UUID
) -> tuple[ProjectFile, Project] | None:
    """A file by its id alone, with the project it is in. Only for a caller that already
    holds the right to it some other way -- a signed link."""
    result = await session.execute(
        select(FileRow, ProjectRow)
        .join(ProjectRow, ProjectRow.id == FileRow.project_id)
        .where(FileRow.id == file_id)
    )
    found = result.one_or_none()
    if found is None:
        return None
    file_row, project_row = found
    return mapper.file_row_to_domain(file_row), mapper.project_row_to_domain(project_row)


async def update_file(
    session: AsyncSession, file_id: UUID, changes: dict[str, Any]
) -> ProjectFile | None:
    row = await session.get(FileRow, file_id)
    if row is None:
        return None

    _apply(row, changes, UPDATABLE_FILE_FIELDS, "file_field_not_updatable")
    await _flush(session)
    await session.refresh(row)
    return mapper.file_row_to_domain(row)


async def delete_file(session: AsyncSession, file_id: UUID) -> bool:
    result = await session.execute(
        delete(FileRow).where(FileRow.id == file_id).returning(FileRow.id)
    )
    return result.scalar_one_or_none() is not None
