from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.invitations.domain import Invitation, InvitationCreate

from . import mapper
from .models import InvitationRow


def _pending(statement, now: datetime):
    return statement.where(
        InvitationRow.accepted_at.is_(None),
        InvitationRow.revoked_at.is_(None),
        InvitationRow.expires_at > now,
    )


async def create(session: AsyncSession, invitation: InvitationCreate) -> Invitation:
    row = mapper.domain_create_to_row(invitation)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def get_by_token_hash(session: AsyncSession, token_hash: str) -> Invitation | None:
    result = await session.execute(
        select(InvitationRow).where(InvitationRow.token_hash == token_hash)
    )
    row = result.scalar_one_or_none()
    return mapper.row_to_domain(row) if row else None


async def get_pending_for_email(
    session: AsyncSession, organization_id: UUID, email_hash: str
) -> Invitation | None:
    statement = _pending(
        select(InvitationRow).where(
            InvitationRow.organization_id == organization_id,
            InvitationRow.email_hash == email_hash,
        ),
        datetime.now(UTC),
    )
    result = await session.execute(statement)
    row = result.scalars().first()
    return mapper.row_to_domain(row) if row else None


async def list_pending_for_organization(
    session: AsyncSession, organization_id: UUID
) -> Sequence[Invitation]:
    statement = _pending(
        select(InvitationRow).where(InvitationRow.organization_id == organization_id),
        datetime.now(UTC),
    ).order_by(InvitationRow.created_at)
    result = await session.execute(statement)
    return [mapper.row_to_domain(row) for row in result.scalars().all()]


async def count_pending_for_organization(
    session: AsyncSession, organization_id: UUID
) -> int:
    statement = _pending(
        select(func.count())
        .select_from(InvitationRow)
        .where(InvitationRow.organization_id == organization_id),
        datetime.now(UTC),
    )
    result = await session.execute(statement)
    return int(result.scalar_one())


async def accept(session: AsyncSession, invitation_id: UUID) -> Invitation | None:
    row = await _row(session, invitation_id)
    if row is None:
        return None

    row.accepted_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(row)
    return mapper.row_to_domain(row)


async def revoke(
    session: AsyncSession, invitation_id: UUID, organization_id: UUID
) -> bool:
    row = await _row(session, invitation_id, organization_id)
    if row is None or row.accepted_at is not None:
        return False

    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await session.flush()
    return True


async def revoke_pending_for_email(
    session: AsyncSession, organization_id: UUID, email_hash: str
) -> int:
    statement = _pending(
        select(InvitationRow).where(
            InvitationRow.organization_id == organization_id,
            InvitationRow.email_hash == email_hash,
        ),
        datetime.now(UTC),
    )
    result = await session.execute(statement)
    rows = result.scalars().all()

    revoked_at = datetime.now(UTC)
    for row in rows:
        row.revoked_at = revoked_at
    if rows:
        await session.flush()
    return len(rows)


async def _row(
    session: AsyncSession,
    invitation_id: UUID,
    organization_id: UUID | None = None,
) -> InvitationRow | None:
    statement = select(InvitationRow).where(InvitationRow.id == invitation_id)
    if organization_id is not None:
        statement = statement.where(InvitationRow.organization_id == organization_id)

    result = await session.execute(statement)
    return result.scalar_one_or_none()
