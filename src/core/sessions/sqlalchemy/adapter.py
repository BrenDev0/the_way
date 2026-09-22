from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.sessions.domain import Session, SessionCreate
from src.core.sessions.sqlalchemy import mapper
from src.core.sessions.sqlalchemy.models import SessionRow


async def create(session: AsyncSession, session_create: SessionCreate) -> Session:
    row = mapper.domain_create_to_row(session_create)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def get_by_token_hash(session: AsyncSession, token_hash: str) -> Session | None:
    result = await session.execute(select(SessionRow).where(SessionRow.token_hash == token_hash))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return mapper.row_to_domain(row)


async def touch(session: AsyncSession, session_id: UUID) -> Session | None:
    result = await session.execute(select(SessionRow).where(SessionRow.id == session_id))
    row = result.scalar_one_or_none()
    if row is None:
        return None
    row.last_seen_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def revoke(session: AsyncSession, session_id: UUID) -> bool:
    result = await session.execute(select(SessionRow).where(SessionRow.id == session_id))
    row = result.scalar_one_or_none()
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await session.flush()
    return True


async def revoke_by_token_hash(session: AsyncSession, token_hash: str) -> bool:
    result = await session.execute(select(SessionRow).where(SessionRow.token_hash == token_hash))
    row = result.scalar_one_or_none()
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await session.flush()
    return True


async def revoke_by_user_id(session: AsyncSession, user_id: UUID) -> int:
    result = await session.execute(
        select(SessionRow).where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
    )
    rows: Sequence[SessionRow] = result.scalars().all()
    revoked_at = datetime.now(UTC)
    for row in rows:
        row.revoked_at = revoked_at
    await session.flush()
    return len(rows)
