from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol
from uuid import UUID

from .domain import (
    Folder,
    FolderCreate,
    Project,
    ProjectContents,
    ProjectCreate,
    ProjectFile,
    ProjectFileCreate,
)

CreateProjectFn = Callable[[ProjectCreate], Awaitable[Project]]
ListProjectsForOwnerFn = Callable[[UUID], Awaitable[Sequence[Project]]]
DeleteProjectFn = Callable[[UUID], Awaitable[bool]]
ListProjectFileIdsFn = Callable[[UUID], Awaitable[Sequence[UUID]]]
ListTreeFn = Callable[[UUID], Awaitable[ProjectContents]]
# The organization's shared library: one per organization. The first reads it (None until
# someone asks for it); the second makes it on first ask, given the name to make it with.
GetLibraryFn = Callable[[UUID], Awaitable[Project | None]]
GetOrCreateLibraryFn = Callable[[UUID, str], Awaitable[Project]]

CreateFolderFn = Callable[[FolderCreate], Awaitable[Folder]]
DeleteFolderFn = Callable[[UUID], Awaitable[bool]]
ListFolderAncestorIdsFn = Callable[[UUID], Awaitable[Sequence[UUID]]]
ListSubtreeFileIdsFn = Callable[[UUID], Awaitable[Sequence[UUID]]]

CreateFileFn = Callable[[ProjectFileCreate], Awaitable[ProjectFile]]
DeleteFileFn = Callable[[UUID], Awaitable[bool]]
# A file by its id alone, with its project: only for a caller that already holds the right
# to it some other way -- a signed link.
GetFileWithProjectFn = Callable[[UUID], Awaitable[tuple[ProjectFile, Project] | None]]


class ListProjectsForOrganizationFn(Protocol):
    async def __call__(
        self, organization_id: UUID, owner_id: UUID | None = None
    ) -> Sequence[Project]: ...


class GetProjectFn(Protocol):
    async def __call__(
        self, project_id: UUID, organization_id: UUID
    ) -> Project | None: ...


class UpdateProjectFn(Protocol):
    async def __call__(
        self, project_id: UUID, changes: dict[str, Any]
    ) -> Project | None: ...


class GetFolderFn(Protocol):
    async def __call__(self, folder_id: UUID, project_id: UUID) -> Folder | None: ...


class UpdateFolderFn(Protocol):
    async def __call__(
        self, folder_id: UUID, changes: dict[str, Any]
    ) -> Folder | None: ...


class GetFileFn(Protocol):
    async def __call__(
        self, file_id: UUID, project_id: UUID
    ) -> ProjectFile | None: ...


class UpdateFileFn(Protocol):
    async def __call__(
        self, file_id: UUID, changes: dict[str, Any]
    ) -> ProjectFile | None: ...


class ListContentsFn(Protocol):
    async def __call__(
        self, project_id: UUID, folder_id: UUID | None
    ) -> ProjectContents: ...


class FindEntryFn(Protocol):
    async def __call__(
        self, project_id: UUID, folder_id: UUID | None, name: str
    ) -> Folder | ProjectFile | None: ...


class ProjectStore(Protocol):
    """Everything the project file system (files.py) reads and writes, in one place.

    The same operations as the single-function ports above, grouped because the file
    system uses nearly all of them within one request. The database implements it
    (sqlalchemy/store.py); a test can implement it with dicts."""

    async def create_project(self, project: ProjectCreate) -> Project: ...

    async def get_library(self, organization_id: UUID) -> Project | None: ...

    async def list_projects_for_owner(self, owner_id: UUID) -> Sequence[Project]: ...

    async def list_contents(
        self, project_id: UUID, folder_id: UUID | None
    ) -> ProjectContents: ...

    async def list_tree(self, project_id: UUID) -> ProjectContents: ...

    async def find_entry(
        self, project_id: UUID, folder_id: UUID | None, name: str
    ) -> Folder | ProjectFile | None: ...

    async def create_folder(self, folder: FolderCreate) -> Folder: ...

    async def get_folder(self, folder_id: UUID, project_id: UUID) -> Folder | None: ...

    async def update_folder(
        self, folder_id: UUID, changes: dict[str, Any]
    ) -> Folder | None: ...

    async def delete_folder(self, folder_id: UUID) -> bool: ...

    async def list_folder_ancestor_ids(self, folder_id: UUID) -> Sequence[UUID]: ...

    async def list_subtree_file_ids(self, folder_id: UUID) -> Sequence[UUID]: ...

    async def create_file(self, project_file: ProjectFileCreate) -> ProjectFile: ...

    async def get_file(self, file_id: UUID, project_id: UUID) -> ProjectFile | None: ...

    async def get_file_with_project(
        self, file_id: UUID
    ) -> tuple[ProjectFile, Project] | None: ...

    async def update_file(
        self, file_id: UUID, changes: dict[str, Any]
    ) -> ProjectFile | None: ...

    async def delete_file(self, file_id: UUID) -> bool: ...
