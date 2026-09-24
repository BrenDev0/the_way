from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol
from uuid import UUID

from .domain import Document, DocumentCreate, DocumentStatus

CreateDocumentFn = Callable[[DocumentCreate], Awaitable[Document]]
CountDocumentsFn = Callable[[UUID], Awaitable[int]]
ListDocumentsForOrganizationFn = Callable[[UUID], Awaitable[Sequence[Document]]]


class GetDocumentFn(Protocol):
    async def __call__(
        self, document_id: UUID, organization_id: UUID
    ) -> Document | None: ...


class GetDocumentTextFn(Protocol):
    async def __call__(
        self, document_id: UUID, organization_id: UUID
    ) -> str | None: ...


class DeleteDocumentFn(Protocol):
    async def __call__(self, document_id: UUID, organization_id: UUID) -> bool: ...


class SaveExtractionFn(Protocol):
    async def __call__(
        self,
        document_id: UUID,
        status: DocumentStatus,
        text: str | None = None,
    ) -> Document | None: ...


class SaveUploadedFn(Protocol):
    async def __call__(
        self, document_id: UUID, organization_id: UUID, size_bytes: int
    ) -> Document | None: ...


class UpdateDocumentFn(Protocol):
    async def __call__(
        self, document_id: UUID, organization_id: UUID, changes: dict[str, Any]
    ) -> Document | None: ...


CountUntrainedFn = Callable[[UUID], Awaitable[int]]
