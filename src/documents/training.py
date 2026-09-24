from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.cryptography.ports import EncryptionService

from . import summaries
from .domain import Document, DocumentStatus
from .sqlalchemy import adapter


async def train_one(
    session: AsyncSession,
    document: Document,
    encryption_service: EncryptionService,
    requested_by: UUID,
) -> bool:
    description: str | None = None

    if not document.description.strip():
        text = await adapter.get_text(session, document.id, document.organization_id)
        if text:
            try:
                description = await summaries.describe(
                    session=session,
                    uploaded_by=requested_by,
                    title=document.title,
                    text=text,
                    encryption_service=encryption_service,
                )
            except Exception:  # noqa: BLE001
                description = None

    await adapter.save_status(
        session, document.id, DocumentStatus.TRAINED, description
    )
    return description is not None


async def train_organization(
    session: AsyncSession,
    organization_id: UUID,
    requested_by: UUID,
    encryption_service: EncryptionService,
) -> tuple[int, int]:
    untrained = await adapter.list_untrained(session, organization_id)

    described = 0
    for document in untrained:
        if await train_one(session, document, encryption_service, requested_by):
            described += 1

    return len(untrained), described
