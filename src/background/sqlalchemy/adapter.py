from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.background.domain import BackgroundTask, BackgroundTaskCreate, TaskStatus

from . import mapper
from .models import BackgroundTaskRow


async def create(session: AsyncSession, task: BackgroundTaskCreate) -> BackgroundTask:
    row = mapper.domain_create_to_row(task)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def get_by_id(session: AsyncSession, task_id: UUID) -> BackgroundTask | None:
    row = await session.get(BackgroundTaskRow, task_id)
    return mapper.row_to_domain(row) if row else None


async def get_for_user(
    session: AsyncSession, task_id: UUID, user_id: UUID
) -> BackgroundTask | None:
    result = await session.execute(
        select(BackgroundTaskRow).where(
            BackgroundTaskRow.id == task_id, BackgroundTaskRow.user_id == user_id
        )
    )
    row = result.scalar_one_or_none()
    return mapper.row_to_domain(row) if row else None


async def list_for_user(session: AsyncSession, user_id: UUID) -> Sequence[BackgroundTask]:
    result = await session.execute(
        select(BackgroundTaskRow)
        .where(BackgroundTaskRow.user_id == user_id)
        .order_by(BackgroundTaskRow.created_at.desc())
    )
    return [mapper.row_to_domain(row) for row in result.scalars().all()]


async def finish(
    session: AsyncSession, task_id: UUID, status: TaskStatus, result: str
) -> BackgroundTask | None:
    row = await session.get(BackgroundTaskRow, task_id)
    if row is None:
        return None

    row.status = status
    row.result = result
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def list_unreported(
    session: AsyncSession, conversation_id: UUID
) -> Sequence[BackgroundTask]:
    result = await session.execute(
        select(BackgroundTaskRow)
        .where(
            BackgroundTaskRow.conversation_id == conversation_id,
            BackgroundTaskRow.status != TaskStatus.RUNNING,
            BackgroundTaskRow.reported.is_(False),
        )
        .order_by(BackgroundTaskRow.updated_at)
    )
    return [mapper.row_to_domain(row) for row in result.scalars().all()]


async def mark_reported(session: AsyncSession, task_ids: Sequence[UUID]) -> None:
    if not task_ids:
        return
    await session.execute(
        update(BackgroundTaskRow)
        .where(BackgroundTaskRow.id.in_(list(task_ids)))
        .values(reported=True)
    )
