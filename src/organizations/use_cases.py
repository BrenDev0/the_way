from datetime import UTC, datetime
from uuid import UUID

from src.core.cache.ports import CacheStore
from src.core.exceptions import NotFoundError, ValidationError
from src.invitations.ports import CountPendingForOrganizationFn
from src.users import use_cases as users_use_cases
from src.users.domain import Role
from src.users.ports import (
    CountUsersForOrganizationFn,
    GetUserByIdFn,
    ListUsersFn,
    UpdateUserRoleFn,
)

from . import cache
from .domain import (
    Organization,
    OrganizationOverview,
    PersonStorage,
    UsageReport,
)
from .ports import (
    DeleteOrganizationByIdFn,
    GetOrganizationByIdFn,
    ListMonthlyUsageFn,
    ListProjectStorageFn,
    UpdateOrganizationByIdFn,
)

# How many of the members' own projects the overview lists, biggest first.
LARGEST_PROJECTS = 8


def _not_found() -> NotFoundError:
    return NotFoundError(message="Organization not found", code="organization_not_found")


def _cache_key(organization_id: UUID) -> str:
    return cache.build_organization_cache_key(
        cache.OrganizationCacheKey.BY_ID,
        organization_id,
    )


async def get_organization(
    organization_id: UUID,
    get_organization_by_id_fn: GetOrganizationByIdFn,
    cache_store: CacheStore,
) -> Organization:
    key = _cache_key(organization_id)

    cached = await cache_store.get_json(key)
    if cached is not None:
        return cache.cache_to_domain(cached)

    organization = await get_organization_by_id_fn(organization_id)
    if organization is None:
        raise _not_found()

    await cache_store.store_json(key, cache.domain_to_cache(organization), cache.CACHE_TTL_SECONDS)
    return organization


async def rename_organization(
    organization_id: UUID,
    name: str,
    update_organization_by_id_fn: UpdateOrganizationByIdFn,
    cache_store: CacheStore,
) -> Organization:
    organization = await update_organization_by_id_fn(organization_id, {"name": name})
    if organization is None:
        raise _not_found()

    await cache_store.store_json(
        _cache_key(organization_id),
        cache.domain_to_cache(organization),
        cache.CACHE_TTL_SECONDS,
    )
    return organization


async def transfer_ownership(
    organization_id: UUID,
    current_owner_id: UUID,
    new_owner_id: UUID,
    get_user_by_id_fn: GetUserByIdFn,
    update_user_role_fn: UpdateUserRoleFn,
    cache_store: CacheStore,
) -> None:
    if new_owner_id == current_owner_id:
        raise ValidationError(
            message="You already own this organization",
            code="already_organization_owner",
        )

    new_owner = await get_user_by_id_fn(new_owner_id)
    if new_owner is None or new_owner.organization_id != organization_id:
        raise NotFoundError(message="User not found", code="user_not_found")

    await update_user_role_fn(new_owner_id, Role.OWNER)
    await update_user_role_fn(current_owner_id, Role.ADMIN)

    await users_use_cases.evict_user(new_owner_id, cache_store)
    await users_use_cases.evict_user(current_owner_id, cache_store)


async def delete_organization(
    organization_id: UUID,
    delete_organization_by_id_fn: DeleteOrganizationByIdFn,
    cache_store: CacheStore,
) -> None:
    deleted = await delete_organization_by_id_fn(organization_id)
    if not deleted:
        raise _not_found()

    await cache_store.remove(_cache_key(organization_id))


async def get_overview(
    organization_id: UUID,
    get_organization_by_id_fn: GetOrganizationByIdFn,
    count_users_for_organization_fn: CountUsersForOrganizationFn,
    count_pending_for_organization_fn: CountPendingForOrganizationFn,
    list_users_fn: ListUsersFn,
    list_project_storage_fn: ListProjectStorageFn,
) -> OrganizationOverview:
    """Seats in use, who owns the organization, where the storage goes, and the projects
    left without an owner when someone was removed -- to reassign or delete."""
    organization = await get_organization_by_id_fn(organization_id)
    if organization is None:
        raise _not_found()

    members = await count_users_for_organization_fn(organization.id)
    pending = await count_pending_for_organization_fn(organization.id)
    owners = [user for user in await list_users_fn(organization.id) if user.role == Role.OWNER]
    projects = list(await list_project_storage_fn(organization.id))

    # [projects, files, bytes] per owner; projects with no owner belong to no one
    totals: dict[UUID, list[int]] = {}
    for project in projects:
        if project.owner_id is not None:
            entry = totals.setdefault(project.owner_id, [0, 0, 0])
            entry[0] += 1
            entry[1] += project.files
            entry[2] += project.bytes
    by_person = sorted(
        (PersonStorage(user_id, *entry) for user_id, entry in totals.items()),
        key=lambda person: -person.bytes,
    )

    return OrganizationOverview(
        seat_limit=organization.seat_limit,
        members=members,
        pending_invitations=pending,
        owner_id=owners[0].id if owners else None,
        total_files=sum(project.files for project in projects),
        total_bytes=sum(project.bytes for project in projects),
        library=next((project for project in projects if project.shared), None),
        by_person=by_person,
        largest=[project for project in projects if not project.shared][:LARGEST_PROJECTS],
        orphans=[project for project in projects if project.owner_id is None and not project.shared],
    )


def month_starts(now: datetime, months: int) -> list[datetime]:
    """The first instant (UTC) of each of the last `months` calendar months, oldest first."""
    year, month = now.year, now.month
    starts = []
    for _ in range(months):
        starts.append(datetime(year, month, 1, tzinfo=UTC))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return list(reversed(starts))


async def get_usage(
    organization_id: UUID,
    months: int,
    now: datetime,
    list_monthly_usage_fn: ListMonthlyUsageFn,
) -> UsageReport:
    """AI use per person and month: conversations and tokens -- read, written, and read
    from the prompt cache. A conversation counts in the month it started."""
    starts = month_starts(now, months)
    rows = await list_monthly_usage_fn(organization_id, starts[0])
    return UsageReport(months=[start.date() for start in starts], rows=rows)
