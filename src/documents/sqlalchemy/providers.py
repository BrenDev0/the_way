from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database.sqlalchemy import dependencies as db_dependencies
from src.documents.domain import DocumentCreate
from src.documents.ports import (
    CountDocumentsFn,
    CountUntrainedFn,
    CreateDocumentFn,
    DeleteDocumentFn,
    GetDocumentFn,
    GetDocumentTextFn,
    ListDocumentsForOrganizationFn,
    SaveUploadedFn,
    UpdateDocumentFn,
)

from . import adapter

Session = Annotated[AsyncSession, Depends(db_dependencies.get_db_session)]


def provide_create_document_fn(session: Session) -> CreateDocumentFn:
    async def create_document_fn(document: DocumentCreate):
        return await adapter.create(session, document)

    return create_document_fn


def provide_count_documents_fn(session: Session) -> CountDocumentsFn:
    async def count_documents_fn(organization_id: UUID):
        return await adapter.count_for_organization(session, organization_id)

    return count_documents_fn


def provide_list_documents_for_organization_fn(
    session: Session,
) -> ListDocumentsForOrganizationFn:
    async def list_documents_for_organization_fn(organization_id: UUID):
        return await adapter.list_for_organization(session, organization_id)

    return list_documents_for_organization_fn


def provide_get_document_fn(session: Session) -> GetDocumentFn:
    async def get_document_fn(document_id: UUID, organization_id: UUID):
        return await adapter.get_for_organization(session, document_id, organization_id)

    return get_document_fn


def provide_get_document_text_fn(session: Session) -> GetDocumentTextFn:
    async def get_document_text_fn(document_id: UUID, organization_id: UUID):
        return await adapter.get_text(session, document_id, organization_id)

    return get_document_text_fn


def provide_save_uploaded_fn(session: Session) -> SaveUploadedFn:
    async def save_uploaded_fn(document_id: UUID, organization_id: UUID, size_bytes: int):
        return await adapter.save_uploaded(session, document_id, organization_id, size_bytes)

    return save_uploaded_fn


def provide_delete_document_fn(session: Session) -> DeleteDocumentFn:
    async def delete_document_fn(document_id: UUID, organization_id: UUID):
        return await adapter.delete_for_organization(session, document_id, organization_id)

    return delete_document_fn


def provide_update_document_fn(session: Session) -> UpdateDocumentFn:
    async def update_document_fn(
        document_id: UUID, organization_id: UUID, changes: dict[str, Any]
    ):
        return await adapter.update_for_organization(
            session, document_id, organization_id, changes
        )

    return update_document_fn


def provide_count_untrained_fn(session: Session) -> CountUntrainedFn:
    async def count_untrained_fn(organization_id: UUID):
        return await adapter.count_untrained(session, organization_id)

    return count_untrained_fn
