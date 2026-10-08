"""The organization tab's numbers: seats, storage, orphaned projects and AI use."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update

from src.conversations.sqlalchemy.models import ConversationRow
from src.organizations import overview
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.organizations.sqlalchemy.models import OrganizationRow
from src.projects.domain import FileStatus, ProjectCreate, ProjectFileCreate
from src.projects.sqlalchemy import adapter as projects_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter


async def make_user(db_session, organization_id, role):
    return await users_adapter.create(
        db_session,
        UserCreate(organization_id=organization_id, encrypted_email=f"enc::{uuid4()}@x.com", email_hash=f"h::{uuid4()}", password_hash="pw", role=role),
    )


async def add_file(db_session, project, name, size):
    created = await projects_adapter.create_file(
        db_session, ProjectFileCreate(project_id=project.id, folder_id=None, name=name, content_type="image/png", size_bytes=size)
    )
    await projects_adapter.update_file(db_session, created.id, {"status": FileStatus.READY})


@pytest.fixture
async def org(db_session):
    organization = await organizations_adapter.create(db_session, OrganizationCreate(name="Agencia"))
    await db_session.execute(update(OrganizationRow).where(OrganizationRow.id == organization.id).values(seat_limit=5))
    owner = await make_user(db_session, organization.id, Role.OWNER)
    admin = await make_user(db_session, organization.id, Role.ADMIN)

    mine = await projects_adapter.create_project(db_session, ProjectCreate(organization_id=organization.id, owner_id=admin.id, name="Borradores"))
    await add_file(db_session, mine, "a.png", 1_000)
    await add_file(db_session, mine, "b.png", 3_000)
    orphan = await projects_adapter.create_project(db_session, ProjectCreate(organization_id=organization.id, owner_id=admin.id, name="De alguien que se fue"))
    await add_file(db_session, orphan, "c.png", 500)
    await projects_adapter.update_project(db_session, orphan.id, {"owner_id": None})
    library = await projects_adapter.get_or_create_library(db_session, organization.id, "Biblioteca")
    await add_file(db_session, library, "logo.png", 200)

    now = datetime.now(UTC)
    for user, created, tokens in [(owner, now, (100, 10)), (owner, now - timedelta(days=1), (50, 5)), (admin, now - timedelta(days=70), (900, 90))]:
        db_session.add(ConversationRow(
            organization_id=organization.id, user_id=user.id, title="t", status="idle", pending_tool_calls=[], completed_tool_results=[],
            iterations_used=0, input_tokens=tokens[0], output_tokens=tokens[1], total_tokens=sum(tokens), cache_read_tokens=7, cache_write_tokens=3,
            created_at=created,
        ))
    await db_session.commit()
    return organization, owner, admin, orphan


async def test_the_overview_counts_seats_storage_and_orphans(db_session, org):
    organization, owner, admin, orphan = org

    result = await overview.overview_route(admin, db_session)

    assert result["seats"] == {"limit": 5, "members": 2, "pending": 0}
    assert result["ownerId"] == str(owner.id)
    assert result["storage"]["bytes"] == 4_700 and result["storage"]["files"] == 4
    assert result["storage"]["library"] == {"files": 1, "bytes": 200}
    assert result["storage"]["byPerson"] == [{"id": str(admin.id), "projects": 1, "files": 2, "bytes": 4_000}]
    assert [p["name"] for p in result["orphans"]] == ["De alguien que se fue"]
    assert result["orphans"][0]["bytes"] == 500
    assert "Biblioteca" not in [p["name"] for p in result["storage"]["largest"]]


async def test_usage_is_counted_per_person_and_month(db_session, org):
    _, owner, admin, _ = org

    result = await overview.usage_route(owner, db_session, months=6)

    assert len(result["months"]) == 6 and result["months"][-1] == datetime.now(UTC).date().replace(day=1).isoformat()
    by_user = {}
    for row in result["rows"]:
        by_user.setdefault(row["userId"], []).append(row)
    owner_rows = by_user[str(owner.id)]
    assert sum(r["conversations"] for r in owner_rows) == 2
    assert sum(r["input"] for r in owner_rows) == 150 and sum(r["output"] for r in owner_rows) == 15
    assert sum(r["cacheRead"] for r in owner_rows) == 14
    assert by_user[str(admin.id)][0]["input"] == 900


def test_months_step_back_over_the_year_end():
    starts = overview.month_starts(datetime(2026, 2, 10, tzinfo=UTC), 4)

    assert [s.date().isoformat() for s in starts] == ["2025-11-01", "2025-12-01", "2026-01-01", "2026-02-01"]
