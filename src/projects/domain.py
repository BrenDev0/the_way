from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class FileStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"


@dataclass
class Project:
    id: UUID
    organization_id: UUID
    owner_id: UUID | None
    name: str
    created_at: datetime
    updated_at: datetime
    # the organization's library (config.LIBRARY_PROJECT), not anyone's own project
    shared: bool = False


@dataclass
class ProjectCreate:
    organization_id: UUID
    owner_id: UUID
    name: str


@dataclass
class Folder:
    id: UUID
    project_id: UUID
    parent_id: UUID | None
    name: str
    created_at: datetime
    updated_at: datetime


@dataclass
class FolderCreate:
    project_id: UUID
    parent_id: UUID | None
    name: str


@dataclass
class ProjectFile:
    id: UUID
    project_id: UUID
    folder_id: UUID | None
    name: str
    content_type: str
    size_bytes: int
    status: FileStatus
    uploaded_by: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass
class ProjectFileCreate:
    project_id: UUID
    folder_id: UUID | None
    name: str
    content_type: str
    size_bytes: int
    uploaded_by: UUID | None = None


@dataclass
class ProjectContents:
    folders: Sequence[Folder]
    files: Sequence[ProjectFile]
