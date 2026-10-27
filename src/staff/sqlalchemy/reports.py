"""The queries behind the staff panel's view of every organization.

Read-only aggregates over tables other slices own -- organizations, users, invitations,
sessions and project files -- counted in SQL, so the list does not load every row. Like
organizations/sqlalchemy/reports.py, the one place in this slice that reaches into other
slices' models.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, and_, case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api_keys import config as api_keys_config
from src.api_keys.sqlalchemy.models import ApiKeyRow
from src.invitations.sqlalchemy.models import InvitationRow
from src.organizations.sqlalchemy.models import OrganizationRow
from src.projects.domain import FileStatus
from src.projects.sqlalchemy.models import FileRow, ProjectRow
from src.sessions.sqlalchemy.models import SessionRow
from src.staff.domain import OrganizationMember, OrganizationSummary
from src.users.domain import Role
from src.users.sqlalchemy.models import UserRow


def _summaries() -> Select:
    """Every organization with its counts, one row each, newest first."""
    members = (
        select(UserRow.organization_id.label("organization_id"), func.count().label("n"))
        .group_by(UserRow.organization_id)
        .subquery()
    )
    pending = (
        select(InvitationRow.organization_id.label("organization_id"), func.count().label("n"))
        .where(
            InvitationRow.accepted_at.is_(None),
            InvitationRow.revoked_at.is_(None),
            InvitationRow.expires_at > datetime.now(UTC),
        )
        .group_by(InvitationRow.organization_id)
        .subquery()
    )
    storage = (
        select(
            ProjectRow.organization_id.label("organization_id"),
            func.count(FileRow.id).label("files"),
            func.coalesce(func.sum(FileRow.size_bytes), 0).label("bytes"),
        )
        .select_from(ProjectRow)
        .join(FileRow, and_(FileRow.project_id == ProjectRow.id, FileRow.status == FileStatus.READY.value))
        .group_by(ProjectRow.organization_id)
        .subquery()
    )
    seen = (
        select(UserRow.organization_id.label("organization_id"), func.max(SessionRow.last_seen_at).label("seen"))
        .select_from(UserRow)
        .join(SessionRow, SessionRow.user_id == UserRow.id)
        .group_by(UserRow.organization_id)
        .subquery()
    )
    # one owner per organization (the oldest account), for the list to name
    owner = (
        select(UserRow.organization_id.label("organization_id"), UserRow.email.label("email"))
        .where(UserRow.role == Role.OWNER.value)
        .distinct(UserRow.organization_id)
        .order_by(UserRow.organization_id, UserRow.created_at)
        .subquery()
    )
    return (
        select(
            OrganizationRow,
            func.coalesce(members.c.n, 0),
            func.coalesce(pending.c.n, 0),
            owner.c.email,
            func.coalesce(storage.c.files, 0),
            func.coalesce(storage.c.bytes, 0),
            seen.c.seen,
            exists()
            .where(
                ApiKeyRow.organization_id == OrganizationRow.id,
                ApiKeyRow.provider.in_([str(provider) for provider in api_keys_config.PROVIDER_PRECEDENCE]),
            )
            .label("ai_enabled"),
        )
        .outerjoin(members, members.c.organization_id == OrganizationRow.id)
        .outerjoin(pending, pending.c.organization_id == OrganizationRow.id)
        .outerjoin(owner, owner.c.organization_id == OrganizationRow.id)
        .outerjoin(storage, storage.c.organization_id == OrganizationRow.id)
        .outerjoin(seen, seen.c.organization_id == OrganizationRow.id)
        .order_by(OrganizationRow.created_at.desc())
    )


def _summary(row) -> OrganizationSummary:
    organization, members, pending, owner_email, files, size, seen, ai_enabled = row
    return OrganizationSummary(
        id=organization.id,
        name=organization.name,
        seat_limit=organization.seat_limit,
        created_at=organization.created_at,
        members=int(members),
        pending_invitations=int(pending),
        owner_encrypted_email=owner_email,
        files=int(files),
        bytes=int(size),
        last_seen_at=seen,
        ai_enabled=bool(ai_enabled),
    )


async def list_summaries(session: AsyncSession) -> list[OrganizationSummary]:
    result = await session.execute(_summaries())
    return [_summary(row) for row in result.all()]


async def get_summary(session: AsyncSession, organization_id: UUID) -> OrganizationSummary | None:
    result = await session.execute(_summaries().where(OrganizationRow.id == organization_id))
    row = result.first()
    return _summary(row) if row else None


async def list_members(session: AsyncSession, organization_id: UUID) -> list[OrganizationMember]:
    """The organization's people: owners first, then admins, then members, each oldest first,
    with when they were last seen on any device."""
    rank = case(
        (UserRow.role == Role.OWNER.value, 0),
        (UserRow.role == Role.ADMIN.value, 1),
        else_=2,
    )
    result = await session.execute(
        select(UserRow, func.max(SessionRow.last_seen_at))
        .outerjoin(SessionRow, SessionRow.user_id == UserRow.id)
        .where(UserRow.organization_id == organization_id)
        .group_by(UserRow.id)
        .order_by(rank, UserRow.created_at)
    )
    return [
        OrganizationMember(
            id=user.id,
            encrypted_email=user.email,
            role=Role(user.role),
            created_at=user.created_at,
            last_seen_at=seen,
        )
        for user, seen in result.all()
    ]
