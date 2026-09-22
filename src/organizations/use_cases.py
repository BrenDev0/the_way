from uuid import UUID

from src.core.cache.ports import CacheStore
from src.core.exceptions import NotFoundError, ValidationError
from src.users import use_cases as users_use_cases
from src.users.domain import Role
from src.users.ports import GetUserByIdFn, UpdateUserRoleFn

from . import cache, mapper
from .domain import Organization
from .ports import (
    DeleteOrganizationByIdFn,
    GetOrganizationByIdFn,
    UpdateOrganizationByIdFn,
)


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
        return mapper.cache_to_domain(cached)

    organization = await get_organization_by_id_fn(organization_id)
    if organization is None:
        raise _not_found()

    await cache_store.store_json(key, mapper.domain_to_cache(organization), cache.CACHE_TTL_SECONDS)
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
        mapper.domain_to_cache(organization),
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
