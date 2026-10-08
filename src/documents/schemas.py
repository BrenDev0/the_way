from datetime import datetime
from uuid import UUID

from pydantic import Field

from src.core.schemas import ApiBaseModel

from .config import MAX_DESCRIPTION_CHARS
from .domain import DocumentStatus


class RequestUploadRequest(ApiBaseModel):
    title: str
    filename: str
    content_type: str
    size_bytes: int = Field(gt=0)
    description: str = Field(default="", min_length=0, max_length=MAX_DESCRIPTION_CHARS)


class DocumentResponse(ApiBaseModel):
    id: UUID
    title: str
    description: str = Field(min_length=0)
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    extracted_chars: int
    uploaded_by: UUID | None
    created_at: datetime
    updated_at: datetime
    # the client brand it is about -- a brand folder in the library -- or none
    brand: str | None = None


class UploadTicketResponse(ApiBaseModel):
    document: DocumentResponse
    upload_url: str
    expires_in_seconds: int


class DeleteDocumentResponse(ApiBaseModel):
    detail: str


class UpdateDocumentRequest(ApiBaseModel):
    title: str | None = None
    description: str | None = Field(
        default=None, min_length=0, max_length=MAX_DESCRIPTION_CHARS
    )
    # "" clears it: the document is about the organization itself, not one client brand
    brand: str | None = Field(default=None, min_length=0, max_length=255)


class TrainDocumentsResponse(ApiBaseModel):
    detail: str
    queued: int
