from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.staff.domain import (
    DeletedOrganization,
    DeletedOrganizationCreate,
    OwnerInvitation,
    OwnerInvitationCreate,
    StaffMember,
    StaffMemberCreate,
    StaffSession,
    StaffSessionCreate,
)

from . import mapper
from .models import (
    DeletedOrganizationRow,
    OwnerInvitationRow,
    StaffMemberRow,
    StaffSessionRow,
)

# --- staff members --------------------------------------------------------------------


async def create_member(session: AsyncSession, member: StaffMemberCreate) -> StaffMember:
    row = mapper.member_create_to_row(member)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return mapper.member_to_domain(row)


async def get_member_by_id(session: AsyncSession, staff_id: UUID) -> StaffMember | None:
    row = await session.get(StaffMemberRow, staff_id)
    return mapper.member_to_domain(row) if row else None


async def get_member_by_email_hash(session: AsyncSession, email_hash: str) -> StaffMember | None:
    result = await session.execute(select(StaffMemberRow).where(StaffMemberRow.email_hash == email_hash))
    row = result.scalar_one_or_none()
    return mapper.member_to_domain(row) if row else None


# --- staff sessions -------------------------------------------------------------------


async def create_session(session: AsyncSession, staff_session: StaffSessionCreate) -> StaffSession:
    row = mapper.session_create_to_row(staff_session)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return mapper.session_to_domain(row)


async def get_session_by_token_hash(session: AsyncSession, token_hash: str) -> StaffSession | None:
    result = await session.execute(select(StaffSessionRow).where(StaffSessionRow.token_hash == token_hash))
    row = result.scalar_one_or_none()
    return mapper.session_to_domain(row) if row else None


async def touch_session(session: AsyncSession, session_id: UUID) -> StaffSession | None:
    row = await session.get(StaffSessionRow, session_id)
    if row is None:
        return None
    row.last_seen_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(row)
    return mapper.session_to_domain(row)


async def revoke_session_by_token_hash(session: AsyncSession, token_hash: str) -> bool:
    result = await session.execute(select(StaffSessionRow).where(StaffSessionRow.token_hash == token_hash))
    row = result.scalar_one_or_none()
    if row is None:
        return False
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await session.flush()
    return True


# --- owner invitations ----------------------------------------------------------------


async def create_invitation(session: AsyncSession, invitation: OwnerInvitationCreate) -> OwnerInvitation:
    row = mapper.invitation_create_to_row(invitation)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return mapper.invitation_to_domain(row)


async def get_invitation_by_token_hash(session: AsyncSession, token_hash: str) -> OwnerInvitation | None:
    result = await session.execute(select(OwnerInvitationRow).where(OwnerInvitationRow.token_hash == token_hash))
    row = result.scalar_one_or_none()
    return mapper.invitation_to_domain(row) if row else None


async def list_invitations(session: AsyncSession) -> Sequence[OwnerInvitation]:
    result = await session.execute(select(OwnerInvitationRow).order_by(OwnerInvitationRow.created_at.desc()))
    return [mapper.invitation_to_domain(row) for row in result.scalars().all()]


async def claim_invitation(session: AsyncSession, invitation_id: UUID, organization_id: UUID) -> bool:
    """One conditional UPDATE: of two requests holding the same link, only one matches."""
    now = datetime.now(UTC)
    result = await session.execute(
        update(OwnerInvitationRow)
        .where(
            OwnerInvitationRow.id == invitation_id,
            OwnerInvitationRow.accepted_at.is_(None),
            OwnerInvitationRow.revoked_at.is_(None),
            OwnerInvitationRow.expires_at > now,
        )
        .values(accepted_at=now, organization_id=organization_id)
        .returning(OwnerInvitationRow.id)
    )
    return result.scalar_one_or_none() is not None


async def revoke_invitation(session: AsyncSession, invitation_id: UUID) -> bool:
    row = await session.get(OwnerInvitationRow, invitation_id)
    if row is None or row.accepted_at is not None:
        return False
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await session.flush()
    return True


async def get_invitation(session: AsyncSession, invitation_id: UUID) -> OwnerInvitation | None:
    row = await session.get(OwnerInvitationRow, invitation_id)
    return mapper.invitation_to_domain(row) if row else None


async def delete_invitation(session: AsyncSession, invitation_id: UUID) -> bool:
    result = await session.execute(
        delete(OwnerInvitationRow).where(OwnerInvitationRow.id == invitation_id).returning(OwnerInvitationRow.id)
    )
    return result.scalar_one_or_none() is not None


async def revoke_pending_invitations_for_email(session: AsyncSession, email_hash: str) -> int:
    now = datetime.now(UTC)
    result = await session.execute(
        select(OwnerInvitationRow).where(
            OwnerInvitationRow.email_hash == email_hash,
            OwnerInvitationRow.accepted_at.is_(None),
            OwnerInvitationRow.revoked_at.is_(None),
            OwnerInvitationRow.expires_at > now,
        )
    )
    rows = result.scalars().all()
    for row in rows:
        row.revoked_at = now
    if rows:
        await session.flush()
    return len(rows)


# --- the record of deleted organizations ----------------------------------------------


async def record_deleted_organization(
    session: AsyncSession, record: DeletedOrganizationCreate
) -> DeletedOrganization:
    row = mapper.deleted_organization_create_to_row(record)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return mapper.deleted_organization_to_domain(row)


async def list_deleted_organizations(session: AsyncSession) -> Sequence[DeletedOrganization]:
    result = await session.execute(select(DeletedOrganizationRow).order_by(DeletedOrganizationRow.created_at.desc()))
    return [mapper.deleted_organization_to_domain(row) for row in result.scalars().all()]
