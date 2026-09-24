from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class DocumentStatus(StrEnum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    TRAINED = "trained"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


@dataclass
class Document:
    id: UUID
    organization_id: UUID
    title: str
    description: str
    filename: str
    content_type: str
    size_bytes: int
    status: DocumentStatus
    extracted_chars: int
    uploaded_by: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass
class DocumentCreate:
    organization_id: UUID
    title: str
    description: str
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: UUID | None = None
