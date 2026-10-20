"""The project file system on the database: ProjectStore, over one session."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.bucket.ports import BucketStore
from src.projects.domain import (
    Folder,
    FolderCreate,
    Project,
    ProjectContents,
    ProjectCreate,
    ProjectFile,
    ProjectFileCreate,
)
from src.projects.files import ProjectFiles

from . import adapter


class SqlProjectStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_project(self, project: ProjectCreate) -> Project:
        return await adapter.create_project(self._session, project)

    async def get_library(self, organization_id: UUID) -> Project | None:
        return await adapter.get_library(self._session, organization_id)

    async def list_projects_for_owner(self, owner_id: UUID) -> Sequence[Project]:
        return await adapter.list_projects_for_owner(self._session, owner_id)

    async def list_contents(self, project_id: UUID, folder_id: UUID | None) -> ProjectContents:
        return await adapter.list_contents(self._session, project_id, folder_id)

    async def list_tree(self, project_id: UUID) -> ProjectContents:
        return await adapter.list_tree(self._session, project_id)

    async def find_entry(
        self, project_id: UUID, folder_id: UUID | None, name: str
    ) -> Folder | ProjectFile | None:
        return await adapter.find_entry(self._session, project_id, folder_id, name)

    async def create_folder(self, folder: FolderCreate) -> Folder:
        return await adapter.create_folder(self._session, folder)

    async def get_folder(self, folder_id: UUID, project_id: UUID) -> Folder | None:
        return await adapter.get_folder(self._session, folder_id, project_id)

    async def update_folder(self, folder_id: UUID, changes: dict[str, Any]) -> Folder | None:
        return await adapter.update_folder(self._session, folder_id, changes)

    async def delete_folder(self, folder_id: UUID) -> bool:
        return await adapter.delete_folder(self._session, folder_id)

    async def list_folder_ancestor_ids(self, folder_id: UUID) -> Sequence[UUID]:
        return await adapter.list_folder_ancestor_ids(self._session, folder_id)

    async def list_subtree_file_ids(self, folder_id: UUID) -> Sequence[UUID]:
        return await adapter.list_subtree_file_ids(self._session, folder_id)

    async def create_file(self, project_file: ProjectFileCreate) -> ProjectFile:
        return await adapter.create_file(self._session, project_file)

    async def get_file(self, file_id: UUID, project_id: UUID) -> ProjectFile | None:
        return await adapter.get_file(self._session, file_id, project_id)

    async def get_file_with_project(self, file_id: UUID) -> tuple[ProjectFile, Project] | None:
        return await adapter.get_file_with_project(self._session, file_id)

    async def update_file(self, file_id: UUID, changes: dict[str, Any]) -> ProjectFile | None:
        return await adapter.update_file(self._session, file_id, changes)

    async def delete_file(self, file_id: UUID) -> bool:
        return await adapter.delete_file(self._session, file_id)


def project_files(
    session: AsyncSession, organization_id: UUID, user_id: UUID, bucket_store: BucketStore
) -> ProjectFiles:
    """One user's project file system, on the database through `session`."""
    return ProjectFiles(SqlProjectStore(session), organization_id, user_id, bucket_store)
