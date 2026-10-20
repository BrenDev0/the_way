"""The queries behind the organization's overview and usage report.

Read-only aggregates over tables other slices own -- projects, files and conversations --
so they are counted in SQL rather than by loading every row. The one place in this slice
that reaches into another slice's models, kept apart from the adapter for that reason.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.conversations.sqlalchemy.models import ConversationRow
from src.projects.domain import FileStatus
from src.projects.sqlalchemy.models import FileRow, ProjectRow

from ..domain import MonthlyUsage, ProjectStorage


async def list_project_storage(session: AsyncSession, organization_id: UUID) -> list[ProjectStorage]:
    """Every project with its file count and size, biggest first."""
    result = await session.execute(
        select(
            ProjectRow.id,
            ProjectRow.name,
            ProjectRow.owner_id,
            ProjectRow.shared,
            ProjectRow.updated_at,
            func.count(FileRow.id),
            func.coalesce(func.sum(FileRow.size_bytes), 0),
        )
        .select_from(ProjectRow)
        .outerjoin(FileRow, and_(FileRow.project_id == ProjectRow.id, FileRow.status == FileStatus.READY.value))
        .where(ProjectRow.organization_id == organization_id)
        .group_by(ProjectRow.id)
        .order_by(func.coalesce(func.sum(FileRow.size_bytes), 0).desc())
    )
    return [
        ProjectStorage(
            id=row[0],
            name=row[1],
            owner_id=row[2],
            shared=bool(row[3]),
            updated_at=row[4],
            files=int(row[5]),
            bytes=int(row[6]),
        )
        for row in result.all()
    ]


async def list_monthly_usage(
    session: AsyncSession, organization_id: UUID, since: datetime
) -> list[MonthlyUsage]:
    """Conversations and tokens per person and month, from `since` on. A conversation
    counts in the month it started."""
    month = func.date_trunc("month", ConversationRow.created_at)
    result = await session.execute(
        select(
            ConversationRow.user_id,
            month,
            func.count(ConversationRow.id),
            func.coalesce(func.sum(ConversationRow.input_tokens), 0),
            func.coalesce(func.sum(ConversationRow.output_tokens), 0),
            func.coalesce(func.sum(ConversationRow.cache_read_tokens), 0),
            func.coalesce(func.sum(ConversationRow.cache_write_tokens), 0),
        )
        .where(ConversationRow.organization_id == organization_id, ConversationRow.created_at >= since)
        .group_by(ConversationRow.user_id, month)
        .order_by(month)
    )
    return [
        MonthlyUsage(
            user_id=row[0],
            month=row[1].date(),
            conversations=int(row[2]),
            input_tokens=int(row[3]),
            output_tokens=int(row[4]),
            cache_read_tokens=int(row[5]),
            cache_write_tokens=int(row[6]),
        )
        for row in result.all()
    ]
