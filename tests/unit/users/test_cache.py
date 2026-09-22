import json
from uuid import uuid4

from helpers import make_user

from src.users import cache, mapper
from src.users import use_cases as users_use_cases
from src.users.domain import Role


def cache_key(user_id):
    return cache.build_user_cache_key(cache.UserCacheKey.BY_ID, user_id)


async def test_get_user_read_through_first_read_populates_the_cache(cache_store):
    user = make_user()

    async def get_fn(user_id):
        return user

    result = await users_use_cases.get_user(user.id, get_fn, cache_store)

    assert result == user
    assert cache_key(user.id) in cache_store.data


async def test_get_user_read_through_cached_read_never_touches_the_database(cache_store):
    user = make_user(role=Role.ADMIN)
    cache_store.data[cache_key(user.id)] = mapper.domain_to_cache(user)

    async def get_fn(user_id):
        raise AssertionError("database must not be queried on a cache hit")

    assert await users_use_cases.get_user(user.id, get_fn, cache_store) == user


async def test_get_user_read_through_repeated_reads_hit_the_database_once(cache_store):
    user = make_user()
    db_reads = []

    async def get_fn(user_id):
        db_reads.append(user_id)
        return user

    for _ in range(5):
        await users_use_cases.get_user(user.id, get_fn, cache_store)

    assert len(db_reads) == 1


async def test_get_user_read_through_entry_expires_after_five_minutes(cache_store):
    user = make_user()

    async def get_fn(user_id):
        return user

    await users_use_cases.get_user(user.id, get_fn, cache_store)

    assert cache_store.ttls[cache_key(user.id)] == cache.CACHE_TTL_SECONDS
    assert cache.CACHE_TTL_SECONDS == 300


async def test_get_user_read_through_a_missing_user_is_not_cached(cache_store):
    user_id = uuid4()

    async def get_fn(_):
        return None

    assert await users_use_cases.get_user(user_id, get_fn, cache_store) is None
    assert cache_key(user_id) not in cache_store.data


async def test_get_user_read_through_each_user_has_its_own_entry(cache_store):
    a, b = make_user(), make_user()
    assert cache_key(a.id) != cache_key(b.id)


async def test_eviction_evict_removes_the_entry(cache_store):
    user = make_user()
    cache_store.data[cache_key(user.id)] = mapper.domain_to_cache(user)

    await users_use_cases.evict_user(user.id, cache_store)

    assert cache_key(user.id) not in cache_store.data


async def test_eviction_evicting_an_uncached_user_is_harmless(cache_store):
    await users_use_cases.evict_user(uuid4(), cache_store)


async def test_eviction_a_read_after_eviction_sees_the_new_role(cache_store):
    user = make_user(role=Role.OWNER)
    cache_store.data[cache_key(user.id)] = mapper.domain_to_cache(user)
    demoted = make_user(user_id=user.id, organization_id=user.organization_id, role=Role.ADMIN)

    async def get_fn(user_id):
        return demoted

    await users_use_cases.evict_user(user.id, cache_store)
    result = await users_use_cases.get_user(user.id, get_fn, cache_store)

    assert result.role is Role.ADMIN


def test_cache_serialisation_round_trips_every_field():
    user = make_user(role=Role.ADMIN)
    assert mapper.cache_to_domain(mapper.domain_to_cache(user)) == user


def test_cache_serialisation_role_survives_as_an_enum_not_a_string():
    user = make_user(role=Role.OWNER)
    restored = mapper.cache_to_domain(mapper.domain_to_cache(user))

    assert restored.role is Role.OWNER
    assert isinstance(restored.role, Role)


def test_cache_serialisation_serialised_form_is_json_safe():
    payload = mapper.domain_to_cache(make_user())
    assert json.loads(json.dumps(payload)) == payload
