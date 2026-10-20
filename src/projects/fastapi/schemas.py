from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field

from src.fastapi.schemas import ApiBaseModel

from ..config import MAX_NAME_CHARS
from ..domain import FileStatus, Folder, Project, ProjectContents, ProjectFile

# The base model demands two characters; a file may be called "a".
Name = Annotated[str, Field(min_length=1, max_length=MAX_NAME_CHARS)]


class CreateProjectRequest(ApiBaseModel):
    name: Name


class RenameRequest(ApiBaseModel):
    name: Name


class TransferProjectRequest(ApiBaseModel):
    new_owner_id: UUID


class ProjectResponse(ApiBaseModel):
    id: UUID
    owner_id: UUID | None
    name: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime
    # the organization's library, which every member reads and owners/admins change
    shared: bool = False

    @classmethod
    def from_domain(cls, project: Project) -> Self:
        return cls(
            id=project.id,
            owner_id=project.owner_id,
            name=project.name,
            created_at=project.created_at,
            updated_at=project.updated_at,
            shared=project.shared,
        )


class CreateFolderRequest(ApiBaseModel):
    name: Name
    parent_id: UUID | None = None


class MoveFolderRequest(ApiBaseModel):
    # Required but nullable: null moves the folder to the project root.
    parent_id: UUID | None


class FolderResponse(ApiBaseModel):
    id: UUID
    project_id: UUID
    parent_id: UUID | None
    name: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, folder: Folder) -> Self:
        return cls(
            id=folder.id,
            project_id=folder.project_id,
            parent_id=folder.parent_id,
            name=folder.name,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )


class RequestFileUploadRequest(ApiBaseModel):
    name: Name
    folder_id: UUID | None = None
    content_type: str
    size_bytes: int = Field(ge=0)


class MoveFileRequest(ApiBaseModel):
    # Required but nullable: null moves the file to the project root.
    folder_id: UUID | None


class FileResponse(ApiBaseModel):
    id: UUID
    project_id: UUID
    folder_id: UUID | None
    name: str = Field(min_length=1)
    content_type: str
    size_bytes: int
    status: FileStatus
    uploaded_by: UUID | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, project_file: ProjectFile) -> Self:
        return cls(
            id=project_file.id,
            project_id=project_file.project_id,
            folder_id=project_file.folder_id,
            name=project_file.name,
            content_type=project_file.content_type,
            size_bytes=project_file.size_bytes,
            status=project_file.status,
            uploaded_by=project_file.uploaded_by,
            created_at=project_file.created_at,
            updated_at=project_file.updated_at,
        )


class FileUploadTicketResponse(ApiBaseModel):
    file: FileResponse
    upload_url: str
    expires_in_seconds: int


class FileDownloadResponse(ApiBaseModel):
    file: FileResponse
    download_url: str
    expires_in_seconds: int


class ProjectContentsResponse(ApiBaseModel):
    folders: list[FolderResponse]
    files: list[FileResponse]

    @classmethod
    def from_domain(cls, contents: ProjectContents) -> Self:
        return cls(
            folders=[FolderResponse.from_domain(folder) for folder in contents.folders],
            files=[FileResponse.from_domain(project_file) for project_file in contents.files],
        )


class DeleteResponse(ApiBaseModel):
    detail: str
