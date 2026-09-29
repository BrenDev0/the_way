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

CreateFolderFn = Callable[[FolderCreate], Awaitable[Folder]]
DeleteFolderFn = Callable[[UUID], Awaitable[bool]]
ListFolderAncestorIdsFn = Callable[[UUID], Awaitable[Sequence[UUID]]]
ListSubtreeFileIdsFn = Callable[[UUID], Awaitable[Sequence[UUID]]]

CreateFileFn = Callable[[ProjectFileCreate], Awaitable[ProjectFile]]
DeleteFileFn = Callable[[UUID], Awaitable[bool]]


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
