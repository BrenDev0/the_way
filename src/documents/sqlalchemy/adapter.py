from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from src.core.exceptions import ValidationError
from src.documents.domain import Document, DocumentCreate, DocumentStatus

from . import mapper
from .models import DocumentRow

WITHOUT_TEXT = defer(DocumentRow.extracted_text)

UPDATABLE_FIELDS = frozenset({"title", "description"})
async def create(session: AsyncSession, document: DocumentCreate) -> Document:
    row = mapper.domain_create_to_row(document)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def count_for_organization(session: AsyncSession, organization_id: UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(DocumentRow)
        .where(DocumentRow.organization_id == organization_id)
    )
    return int(result.scalar_one())


async def list_for_organization(
    session: AsyncSession, organization_id: UUID
) -> Sequence[Document]:
    result = await session.execute(
        select(DocumentRow)
        .options(WITHOUT_TEXT)
        .where(DocumentRow.organization_id == organization_id)
        .order_by(DocumentRow.created_at)
    )
    return [mapper.row_to_domain(row) for row in result.scalars().all()]


async def get_for_organization(
    session: AsyncSession, document_id: UUID, organization_id: UUID
) -> Document | None:
    result = await session.execute(
        select(DocumentRow)
        .options(WITHOUT_TEXT)
        .where(
            DocumentRow.id == document_id,
            DocumentRow.organization_id == organization_id,
        )
    )
    row = result.scalar_one_or_none()
    return mapper.row_to_domain(row) if row else None


async def get_text(
    session: AsyncSession, document_id: UUID, organization_id: UUID
) -> str | None:
    result = await session.execute(
        select(DocumentRow.extracted_text).where(
            DocumentRow.id == document_id,
            DocumentRow.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


async def save_uploaded(
    session: AsyncSession,
    document_id: UUID,
    organization_id: UUID,
    size_bytes: int,
) -> Document | None:
    row = await _row(session, document_id, organization_id)
    if row is None:
        return None

    row.size_bytes = size_bytes
    row.status = DocumentStatus.EXTRACTING
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def save_extraction(
    session: AsyncSession,
    document_id: UUID,
    status: DocumentStatus,
    text: str | None = None,
    description: str | None = None,
) -> Document | None:
    row = await _row(session, document_id)
    if row is None:
        return None

    row.status = status
    row.extracted_text = text
    row.extracted_chars = len(text) if text else 0
    if description is not None:
        row.description = description
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def delete_for_organization(
    session: AsyncSession, document_id: UUID, organization_id: UUID
) -> bool:
    result = await session.execute(
        delete(DocumentRow)
        .where(
            DocumentRow.id == document_id,
            DocumentRow.organization_id == organization_id,
        )
        .returning(DocumentRow.id)
    )
    return result.scalar_one_or_none() is not None


async def _row(
    session: AsyncSession, document_id: UUID, organization_id: UUID | None = None
) -> DocumentRow | None:
    statement = select(DocumentRow).where(DocumentRow.id == document_id)
    if organization_id is not None:
        statement = statement.where(DocumentRow.organization_id == organization_id)

    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def get_by_id(session: AsyncSession, document_id: UUID) -> Document | None:
    result = await session.execute(
        select(DocumentRow).options(WITHOUT_TEXT).where(DocumentRow.id == document_id)
    )
    row = result.scalar_one_or_none()
    return mapper.row_to_domain(row) if row else None


async def update_for_organization(
    session: AsyncSession,
    document_id: UUID,
    organization_id: UUID,
    changes: dict[str, Any],
) -> Document | None:
    unknown = set(changes) - UPDATABLE_FIELDS
    if unknown:
        raise ValidationError(
            message=f"Cannot update: {', '.join(sorted(unknown))}",
            code="document_field_not_updatable",
        )

    row = await _row(session, document_id, organization_id)
    if row is None:
        return None

    for field, value in changes.items():
        setattr(row, field, value)

    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def list_untrained(
    session: AsyncSession, organization_id: UUID
) -> Sequence[Document]:
    result = await session.execute(
        select(DocumentRow)
        .options(WITHOUT_TEXT)
        .where(
            DocumentRow.organization_id == organization_id,
            DocumentRow.status == DocumentStatus.EXTRACTED,
        )
        .order_by(DocumentRow.created_at)
    )
    return [mapper.row_to_domain(row) for row in result.scalars().all()]


async def count_untrained(session: AsyncSession, organization_id: UUID) -> int:
    result = await session.execute(
        select(func.count())
        .select_from(DocumentRow)
        .where(
            DocumentRow.organization_id == organization_id,
            DocumentRow.status == DocumentStatus.EXTRACTED,
        )
    )
    return int(result.scalar_one())


async def save_status(
    session: AsyncSession,
    document_id: UUID,
    status: DocumentStatus,
    description: str | None = None,
) -> Document | None:
    row = await _row(session, document_id)
    if row is None:
        return None

    row.status = status
    if description is not None:
        row.description = description

    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)
