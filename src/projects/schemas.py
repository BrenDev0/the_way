from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import Field

from src.core.schemas import ApiBaseModel

from .config import MAX_NAME_CHARS
from .domain import FileStatus

# The base model demands two characters; a file may be called "a".
Name = Annotated[str, Field(min_length=1, max_length=MAX_NAME_CHARS)]


class CreateProjectRequest(ApiBaseModel):
    name: Name


class RenameRequest(ApiBaseModel):
    name: Name


class ProjectResponse(ApiBaseModel):
    id: UUID
    owner_id: UUID | None
    name: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime


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


class DeleteResponse(ApiBaseModel):
    detail: str
