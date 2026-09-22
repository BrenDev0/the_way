from uuid import UUID

from src.core.cache.ports import CacheStore
from src.core.exceptions import ConflictError
from src.core.sessions import service as sessions_service
from src.core.sessions.ports import RevokeSessionsByUserIdFn

from . import cache, mapper
from .domain import Role, User
from .ports import DeleteUserFn, GetUserByIdFn


def _cache_key(user_id: UUID) -> str:
    return cache.build_user_cache_key(cache.UserCacheKey.BY_ID, user_id)


async def get_user(
    user_id: UUID,
    get_user_by_id_fn: GetUserByIdFn,
    cache_store: CacheStore,
) -> User | None:
    key = _cache_key(user_id)

    cached = await cache_store.get_json(key)
    if cached is not None:
        return mapper.cache_to_domain(cached)

    user = await get_user_by_id_fn(user_id)
    if user is None:
        return None

    await cache_store.store_json(key, mapper.domain_to_cache(user), cache.CACHE_TTL_SECONDS)
    return user


async def evict_user(user_id: UUID, cache_store: CacheStore) -> None:
    await cache_store.remove(_cache_key(user_id))


async def delete_user(
    user_id: UUID,
    role: Role,
    delete_user_fn: DeleteUserFn,
    revoke_sessions_by_user_id_fn: RevokeSessionsByUserIdFn,
    cache_store: CacheStore,
) -> None:
    if role is Role.OWNER:
        raise ConflictError(
            message="Transfer ownership before deleting your account",
            code="owner_must_transfer_ownership",
        )

    await sessions_service.revoke_user_sessions(user_id, revoke_sessions_by_user_id_fn)
    await delete_user_fn(user_id)
    await evict_user(user_id, cache_store)
