"""The organization at a glance, for its owners and admins: seats, storage, the projects
nobody owns any more, and how much AI the team uses.

Read-only aggregates over tables other slices own (users, invitations, projects,
conversations) -- counted here in SQL rather than by loading every row.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.auth import dependencies as auth_dependencies
from src.conversations.sqlalchemy.models import ConversationRow
from src.core.database.sqlalchemy.dependencies import get_db_session
from src.core.exceptions import NotFoundError
from src.invitations.sqlalchemy import adapter as invitations_adapter
from src.projects.domain import FileStatus
from src.projects.sqlalchemy.models import FileRow, ProjectRow
from src.users.domain import Role, User
from src.users.sqlalchemy import adapter as users_adapter

from .sqlalchemy import adapter as organizations_adapter

router = APIRouter(tags=["organizations"])

Manager = Annotated[User, Depends(auth_dependencies.require_role(Role.OWNER, Role.ADMIN))]
Session = Annotated[AsyncSession, Depends(get_db_session)]

MAX_USAGE_MONTHS = 12


def month_starts(now: datetime, months: int) -> list[datetime]:
    """The first instant (UTC) of each of the last `months` calendar months, oldest first."""
    year, month = now.year, now.month
    starts = []
    for _ in range(months):
        starts.append(datetime(year, month, 1, tzinfo=UTC))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return list(reversed(starts))


async def _storage(session: AsyncSession, organization_id: UUID) -> list[dict[str, Any]]:
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
        {
            "id": str(row[0]),
            "name": row[1],
            "ownerId": str(row[2]) if row[2] else None,
            "shared": bool(row[3]),
            "updatedAt": row[4].isoformat(),
            "files": int(row[5]),
            "bytes": int(row[6]),
        }
        for row in result.all()
    ]


@router.get("/me/overview")
async def overview_route(current_user: Manager, session: Session) -> dict[str, Any]:
    """Seats in use, who owns the organization, where the storage goes, and the projects
    left without an owner when someone was removed -- to reassign or delete."""
    organization = await organizations_adapter.get_by_id(session, current_user.organization_id)
    if organization is None:
        raise NotFoundError(message="Organization not found", code="organization_not_found")
    members = await users_adapter.count_for_organization(session, organization.id)
    pending = await invitations_adapter.count_pending_for_organization(session, organization.id)
    owners = [u for u in await users_adapter.list_users(session, organization.id) if u.role == Role.OWNER]
    projects = await _storage(session, organization.id)

    per_person: dict[str, dict[str, int]] = {}
    for project in projects:
        if project["ownerId"]:
            entry = per_person.setdefault(project["ownerId"], {"projects": 0, "files": 0, "bytes": 0})
            entry["projects"] += 1
            entry["files"] += project["files"]
            entry["bytes"] += project["bytes"]

    return {
        "seats": {"limit": organization.seat_limit, "members": members, "pending": pending},
        "ownerId": str(owners[0].id) if owners else None,
        "storage": {
            "bytes": sum(p["bytes"] for p in projects),
            "files": sum(p["files"] for p in projects),
            "library": next(({"files": p["files"], "bytes": p["bytes"]} for p in projects if p["shared"]), None),
            "byPerson": [{"id": person, **entry} for person, entry in sorted(per_person.items(), key=lambda kv: -kv[1]["bytes"])],
            "largest": [p for p in projects if not p["shared"]][:8],
        },
        "orphans": [p for p in projects if p["ownerId"] is None and not p["shared"]],
    }


@router.get("/me/usage")
async def usage_route(
    current_user: Manager,
    session: Session,
    months: Annotated[int, Query(ge=1, le=MAX_USAGE_MONTHS)] = 6,
) -> dict[str, Any]:
    """AI use per person and month: conversations and tokens -- read, written, and read
    from the prompt cache. A conversation counts in the month it started."""
    now = datetime.now(UTC)
    starts = month_starts(now, months)
    start = starts[0]
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
        .where(ConversationRow.organization_id == current_user.organization_id, ConversationRow.created_at >= start)
        .group_by(ConversationRow.user_id, month)
        .order_by(month)
    )
    rows = [
        {
            "userId": str(row[0]),
            "month": row[1].date().isoformat(),
            "conversations": int(row[2]),
            "input": int(row[3]),
            "output": int(row[4]),
            "cacheRead": int(row[5]),
            "cacheWrite": int(row[6]),
        }
        for row in result.all()
    ]
    return {"months": [s.date().isoformat() for s in starts], "rows": rows}
