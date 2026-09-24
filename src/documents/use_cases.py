from collections.abc import Sequence
from typing import Any
from uuid import UUID

from src.core.bucket.domain import BucketError
from src.core.bucket.ports import BucketStore
from src.core.exceptions import (
    ConflictError,
    InternalServerError,
    NotFoundError,
    ValidationError,
)

from . import config, keys
from .domain import Document, DocumentCreate, DocumentStatus
from .ports import (
    CountDocumentsFn,
    CountUntrainedFn,
    CreateDocumentFn,
    DeleteDocumentFn,
    GetDocumentFn,
    ListDocumentsForOrganizationFn,
    SaveUploadedFn,
    UpdateDocumentFn,
)

MEGABYTE = 1024 * 1024


def _not_found() -> NotFoundError:
    return NotFoundError(message="Document not found", code="document_not_found")


def _unavailable() -> InternalServerError:
    return InternalServerError(
        message="Unable to process request at this time",
        code="document_storage_unavailable",
    )


def _too_large() -> ValidationError:
    limit = config.MAX_DOCUMENT_BYTES // MEGABYTE
    return ValidationError(
        message=f"That file is larger than the {limit} MB limit",
        code="document_too_large",
    )


async def request_upload(
    organization_id: UUID,
    title: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    uploaded_by: UUID,
    count_documents_fn: CountDocumentsFn,
    create_document_fn: CreateDocumentFn,
    bucket_store: BucketStore,
    description: str = "",
) -> tuple[Document, str]:
    if size_bytes > config.MAX_DOCUMENT_BYTES:
        raise _too_large()

    held = await count_documents_fn(organization_id)
    if held >= config.MAX_DOCUMENTS_PER_ORGANIZATION:
        raise ConflictError(
            message=(
                "This organization already holds the maximum of "
                f"{config.MAX_DOCUMENTS_PER_ORGANIZATION} documents"
            ),
            code="document_limit_reached",
        )

    document = await create_document_fn(
        DocumentCreate(
            organization_id=organization_id,
            title=title,
            description=description,
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            uploaded_by=uploaded_by,
        )
    )

    try:
        upload_url = await bucket_store.presign_put(
            keys.document_key(organization_id, document.id, filename),
            content_type,
            config.UPLOAD_URL_TTL_SECONDS,
        )
    except BucketError as exc:
        raise _unavailable() from exc

    return document, upload_url


async def complete_upload(
    document_id: UUID,
    organization_id: UUID,
    get_document_fn: GetDocumentFn,
    save_uploaded_fn: SaveUploadedFn,
    bucket_store: BucketStore,
) -> Document:
    document = await get_document_fn(document_id, organization_id)
    if document is None:
        raise _not_found()

    key = keys.document_key(organization_id, document.id, document.filename)

    try:
        stored = [obj for obj in await bucket_store.list(key) if obj.key == key]
    except BucketError as exc:
        raise _unavailable() from exc

    if not stored:
        raise ConflictError(
            message="No file has been uploaded for this document yet",
            code="document_not_uploaded",
        )

    size_bytes = stored[0].size
    if size_bytes > config.MAX_DOCUMENT_BYTES:
        raise _too_large()

    updated = await save_uploaded_fn(document_id, organization_id, size_bytes)
    if updated is None:
        raise _not_found()
    return updated


async def list_documents(
    organization_id: UUID,
    list_documents_for_organization_fn: ListDocumentsForOrganizationFn,
) -> Sequence[Document]:
    return await list_documents_for_organization_fn(organization_id)


async def get_document(
    document_id: UUID,
    organization_id: UUID,
    get_document_fn: GetDocumentFn,
) -> Document:
    document = await get_document_fn(document_id, organization_id)
    if document is None:
        raise _not_found()
    return document


async def delete_document(
    document_id: UUID,
    organization_id: UUID,
    get_document_fn: GetDocumentFn,
    delete_document_fn: DeleteDocumentFn,
    bucket_store: BucketStore,
) -> None:
    document = await get_document_fn(document_id, organization_id)
    if document is None:
        raise _not_found()

    if not await delete_document_fn(document_id, organization_id):
        raise _not_found()

    try:
        await bucket_store.delete(
            keys.document_key(organization_id, document.id, document.filename)
        )
    except BucketError as exc:
        raise _unavailable() from exc


def classify(text: str) -> DocumentStatus:
    if len(text.strip()) < config.MIN_EXTRACTED_CHARS:
        return DocumentStatus.UNSUPPORTED
    return DocumentStatus.EXTRACTED


async def update_document(
    document_id: UUID,
    organization_id: UUID,
    update_document_fn: UpdateDocumentFn,
    title: str | None = None,
    description: str | None = None,
) -> Document:
    changes: dict[str, Any] = {}
    if title is not None:
        changes["title"] = title
    if description is not None:
        changes["description"] = description

    if not changes:
        raise ValidationError(
            message="Supply a title or a description to change",
            code="document_no_changes",
        )

    document = await update_document_fn(document_id, organization_id, changes)
    if document is None:
        raise _not_found()
    return document


async def count_untrained(
    organization_id: UUID,
    count_untrained_fn: CountUntrainedFn,
) -> int:
    queued = await count_untrained_fn(organization_id)
    if queued == 0:
        raise ConflictError(
            message="Every document is already trained",
            code="document_nothing_to_train",
        )
    return queued
