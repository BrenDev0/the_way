import asyncio
import tempfile
from pathlib import Path
from typing import Annotated
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from taskiq import TaskiqDepends

from src.core.bucket.domain import BucketError
from src.core.bucket.ports import BucketStore
from src.core.cryptography.ports import EncryptionService
from src.core.database.sqlalchemy.core import async_session_factory
from src.core.tasks.broker import broker
from src.worker import dependencies as worker_dependencies

from . import config, extraction, keys, training
from . import use_cases as documents_use_cases
from .domain import Document, DocumentStatus
from .sqlalchemy import adapter


async def wait_for_upload(session: AsyncSession, document_id: UUID) -> Document | None:
    for attempt in range(config.READY_ATTEMPTS):
        document = await adapter.get_by_id(session, document_id)
        if document and document.status is DocumentStatus.EXTRACTING:
            return document
        if attempt + 1 == config.READY_ATTEMPTS:
            return None
        await session.rollback()
        await asyncio.sleep(config.READY_INTERVAL_SECONDS)
    return None


@broker.task
async def ingest_document(
    document_id: UUID,
    bucket_store: Annotated[
        BucketStore,
        TaskiqDepends(worker_dependencies.get_bucket_store),
    ],
) -> str | None:
    return await run_ingestion(document_id, bucket_store)


async def run_ingestion(document_id: UUID, bucket_store: BucketStore) -> str | None:
    async with async_session_factory() as session:
        try:
            document = await wait_for_upload(session, document_id)
            if document is None:
                return None

            status, text = await _extract(document, bucket_store)
            await adapter.save_extraction(session, document_id, status, text)
            await session.commit()
            return status
        except Exception:
            await session.rollback()
            await _mark_failed(document_id)
            raise


async def _extract(
    document: Document, bucket_store: BucketStore
) -> tuple[DocumentStatus, str | None]:
    key = keys.document_key(document.organization_id, document.id, document.filename)
    suffix = extraction.suffix_of(document.filename)

    with tempfile.TemporaryDirectory() as workspace:
        source = Path(workspace) / f"{document.id}{suffix}"
        try:
            await bucket_store.get(key, source)
        except BucketError:
            return DocumentStatus.FAILED, None

        try:
            text = await asyncio.to_thread(extraction.extract, source, document.filename)
        except extraction.UnsupportedDocument:
            return DocumentStatus.UNSUPPORTED, None
        except Exception:  # noqa: BLE001
            return DocumentStatus.FAILED, None

    status = documents_use_cases.classify(text)
    return status, text if status is DocumentStatus.EXTRACTED else None


async def _mark_failed(document_id: UUID) -> None:
    async with async_session_factory() as session:
        await adapter.save_extraction(session, document_id, DocumentStatus.FAILED, None)
        await session.commit()


@broker.task
async def train_documents(
    organization_id: UUID,
    requested_by: UUID,
    encryption_service: Annotated[
        EncryptionService,
        TaskiqDepends(worker_dependencies.get_encryption_service),
    ],
) -> str:
    return await run_training(organization_id, requested_by, encryption_service)


async def run_training(
    organization_id: UUID,
    requested_by: UUID,
    encryption_service: EncryptionService,
) -> str:
    async with async_session_factory() as session:
        try:
            trained, described = await training.train_organization(
                session, organization_id, requested_by, encryption_service
            )
            await session.commit()
            return f"trained {trained}, described {described}"
        except Exception:
            await session.rollback()
            raise
