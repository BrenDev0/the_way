"""The overview and usage use cases, over fake read ports."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from helpers import make_organization, make_user

from src.core.exceptions import NotFoundError
from src.organizations import use_cases as organizations_use_cases
from src.organizations.domain import MonthlyUsage, ProjectStorage
from src.users.domain import Role

NOW = datetime(2026, 2, 10, tzinfo=UTC)


def storage(name, owner_id, bytes_, files=1, shared=False):
    return ProjectStorage(
        id=uuid4(), name=name, owner_id=owner_id, shared=shared, updated_at=NOW, files=files, bytes=bytes_
    )


async def overview_of(*, projects, users=(), organization="given", members=2, pending=0):
    organization = make_organization(seat_limit=5) if organization == "given" else organization

    async def get_organization(_):
        return organization

    async def count_users(_):
        return members

    async def count_pending(_):
        return pending

    async def list_users(_):
        return list(users)

    async def list_storage(_):
        return list(projects)

    return await organizations_use_cases.get_overview(
        organization_id=uuid4(),
        get_organization_by_id_fn=get_organization,
        count_users_for_organization_fn=count_users,
        count_pending_for_organization_fn=count_pending,
        list_users_fn=list_users,
        list_project_storage_fn=list_storage,
    )


async def test_seats_come_from_the_organization_and_the_counts():
    result = await overview_of(projects=[], members=3, pending=1)

    assert (result.seat_limit, result.members, result.pending_invitations) == (5, 3, 1)


async def test_an_organization_that_does_not_exist_is_not_found():
    with pytest.raises(NotFoundError) as exc:
        await overview_of(projects=[], organization=None)

    assert exc.value.code == "organization_not_found"


async def test_the_owner_is_the_first_user_with_the_owner_role():
    owner = make_user(role=Role.OWNER)

    result = await overview_of(projects=[], users=[make_user(role=Role.ADMIN), owner])

    assert result.owner_id == owner.id


async def test_with_no_owner_there_is_no_owner_id():
    result = await overview_of(projects=[], users=[make_user(role=Role.ADMIN)])

    assert result.owner_id is None


async def test_storage_adds_up_per_person_biggest_first():
    small, big = uuid4(), uuid4()
    projects = [
        storage("a", big, 3_000, files=3),
        storage("b", small, 500, files=1),
        storage("c", big, 1_000, files=2),
    ]

    result = await overview_of(projects=projects)

    assert [(p.user_id, p.projects, p.files, p.bytes) for p in result.by_person] == [
        (big, 2, 5, 4_000),
        (small, 1, 1, 500),
    ]
    assert (result.total_files, result.total_bytes) == (6, 4_500)


async def test_the_library_is_counted_in_the_total_but_belongs_to_no_one():
    owner = uuid4()
    library = storage("Biblioteca", None, 200, shared=True)

    result = await overview_of(projects=[storage("mine", owner, 800), library])

    assert result.library == library
    assert result.total_bytes == 1_000
    assert [p.user_id for p in result.by_person] == [owner]
    assert library not in result.largest
    assert library not in result.orphans


async def test_a_project_nobody_owns_any_more_is_an_orphan():
    orphan = storage("De alguien que se fue", None, 500)

    result = await overview_of(projects=[storage("mine", uuid4(), 800), orphan])

    assert result.orphans == [orphan]


async def test_only_the_biggest_projects_are_listed():
    projects = [storage(f"p{i}", uuid4(), 1_000 - i) for i in range(12)]

    result = await overview_of(projects=projects)

    assert [p.name for p in result.largest] == [f"p{i}" for i in range(organizations_use_cases.LARGEST_PROJECTS)]


def test_months_step_back_over_the_year_end():
    starts = organizations_use_cases.month_starts(NOW, 4)

    assert [s.date().isoformat() for s in starts] == ["2025-11-01", "2025-12-01", "2026-01-01", "2026-02-01"]
    assert all(s.tzinfo is UTC for s in starts)


async def test_usage_asks_from_the_oldest_month_and_names_every_month():
    asked = []
    row = MonthlyUsage(uuid4(), date(2026, 2, 1), 2, 150, 15, 14, 6)

    async def list_usage(organization_id, since):
        asked.append(since)
        return [row]

    report = await organizations_use_cases.get_usage(uuid4(), 3, NOW, list_usage)

    assert asked == [datetime(2025, 12, 1, tzinfo=UTC)]
    assert list(report.months) == [date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1)]
    assert list(report.rows) == [row]
