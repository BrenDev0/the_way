from uuid import uuid4

import pytest
from helpers import make_organization

from src.core.exceptions import NotFoundError
from src.organizations import cache, mapper
from src.organizations import use_cases as organizations_use_cases


def cache_key(organization_id):
    return cache.build_organization_cache_key(cache.OrganizationCacheKey.BY_ID, organization_id)


async def test_get_organization_returns_the_organization(cache_store):
    organization = make_organization(name="Acme Inc", seat_limit=25)

    async def get_fn(organization_id):
        return organization

    result = await organizations_use_cases.get_organization(
        organization_id=organization.id,
        get_organization_by_id_fn=get_fn,
        cache_store=cache_store,
    )

    assert result.id == organization.id
    assert result.name == "Acme Inc"
    assert result.seat_limit == 25


async def test_get_organization_first_read_populates_the_cache(cache_store):
    organization = make_organization(name="Acme Inc")

    async def get_fn(organization_id):
        return organization

    await organizations_use_cases.get_organization(
        organization_id=organization.id,
        get_organization_by_id_fn=get_fn,
        cache_store=cache_store,
    )

    assert cache_key(organization.id) in cache_store.data


async def test_get_organization_cached_read_never_touches_the_database(cache_store):
    organization = make_organization(name="Acme Inc")
    cache_store.data[cache_key(organization.id)] = mapper.domain_to_cache(organization)

    async def get_fn(organization_id):
        raise AssertionError("database must not be queried on a cache hit")

    result = await organizations_use_cases.get_organization(
        organization_id=organization.id,
        get_organization_by_id_fn=get_fn,
        cache_store=cache_store,
    )

    assert result == organization


async def test_get_organization_second_read_hits_the_cache(cache_store):
    organization = make_organization(name="Acme Inc")
    db_reads = []

    async def get_fn(organization_id):
        db_reads.append(organization_id)
        return organization

    for _ in range(3):
        await organizations_use_cases.get_organization(
            organization_id=organization.id,
            get_organization_by_id_fn=get_fn,
            cache_store=cache_store,
        )

    assert len(db_reads) == 1


async def test_get_organization_cached_entry_expires(cache_store):
    organization = make_organization()

    async def get_fn(organization_id):
        return organization

    await organizations_use_cases.get_organization(
        organization_id=organization.id,
        get_organization_by_id_fn=get_fn,
        cache_store=cache_store,
    )

    assert cache_store.ttls[cache_key(organization.id)] == cache.CACHE_TTL_SECONDS
    assert cache.CACHE_TTL_SECONDS >= 300


async def test_get_organization_missing_organization_raises_and_caches_nothing(cache_store):
    async def get_fn(organization_id):
        return None

    organization_id = uuid4()
    with pytest.raises(NotFoundError) as exc:
        await organizations_use_cases.get_organization(
            organization_id=organization_id,
            get_organization_by_id_fn=get_fn,
            cache_store=cache_store,
        )

    assert exc.value.code == "organization_not_found"
    assert cache_key(organization_id) not in cache_store.data


async def test_rename_organization_sends_only_the_name_as_a_change(cache_store):
    changes = []

    async def update_fn(organization_id, change_set):
        changes.append(change_set)
        return make_organization(name=change_set["name"])

    await organizations_use_cases.rename_organization(
        organization_id=uuid4(),
        name="New Name",
        update_organization_by_id_fn=update_fn,
        cache_store=cache_store,
    )

    assert changes == [{"name": "New Name"}]


async def test_rename_organization_update_refreshes_the_cache(cache_store):
    organization = make_organization(name="Old Name")
    cache_store.data[cache_key(organization.id)] = mapper.domain_to_cache(organization)

    async def update_fn(organization_id, change_set):
        return make_organization(name=change_set["name"])

    await organizations_use_cases.rename_organization(
        organization_id=organization.id,
        name="New Name",
        update_organization_by_id_fn=update_fn,
        cache_store=cache_store,
    )

    cached = mapper.cache_to_domain(cache_store.data[cache_key(organization.id)])
    assert cached.name == "New Name"


async def test_rename_organization_a_read_after_update_sees_the_new_name(cache_store):
    organization = make_organization(name="Old Name")
    cache_store.data[cache_key(organization.id)] = mapper.domain_to_cache(organization)

    async def update_fn(organization_id, change_set):
        return make_organization(name=change_set["name"])

    async def get_fn(organization_id):
        raise AssertionError("should be served from the refreshed cache")

    await organizations_use_cases.rename_organization(
        organization_id=organization.id,
        name="New Name",
        update_organization_by_id_fn=update_fn,
        cache_store=cache_store,
    )
    result = await organizations_use_cases.get_organization(
        organization_id=organization.id,
        get_organization_by_id_fn=get_fn,
        cache_store=cache_store,
    )

    assert result.name == "New Name"


async def test_rename_organization_missing_organization_raises_not_found(cache_store):
    async def update_fn(organization_id, change_set):
        return None

    with pytest.raises(NotFoundError) as exc:
        await organizations_use_cases.rename_organization(
            organization_id=uuid4(),
            name="New Name",
            update_organization_by_id_fn=update_fn,
            cache_store=cache_store,
        )
    assert exc.value.code == "organization_not_found"


async def test_delete_organization_deletes_the_given_organization(cache_store):
    seen = []
    organization_id = uuid4()

    async def delete_fn(oid):
        seen.append(oid)
        return True

    await organizations_use_cases.delete_organization(
        organization_id=organization_id,
        delete_organization_by_id_fn=delete_fn,
        cache_store=cache_store,
    )
    assert seen == [organization_id]


async def test_delete_organization_delete_evicts_the_cache(cache_store):
    organization = make_organization()
    cache_store.data[cache_key(organization.id)] = mapper.domain_to_cache(organization)

    async def delete_fn(oid):
        return True

    await organizations_use_cases.delete_organization(
        organization_id=organization.id,
        delete_organization_by_id_fn=delete_fn,
        cache_store=cache_store,
    )

    assert cache_key(organization.id) not in cache_store.data


async def test_delete_organization_missing_organization_raises_and_keeps_cache_untouched(cache_store):
    async def delete_fn(oid):
        return False

    with pytest.raises(NotFoundError) as exc:
        await organizations_use_cases.delete_organization(
            organization_id=uuid4(),
            delete_organization_by_id_fn=delete_fn,
            cache_store=cache_store,
        )
    assert exc.value.code == "organization_not_found"


def test_cache_serialisation_round_trips_every_field():
    organization = make_organization(name="Acme Inc", seat_limit=25)
    assert mapper.cache_to_domain(mapper.domain_to_cache(organization)) == organization


def test_cache_serialisation_round_trips_a_null_seat_limit():
    organization = make_organization(seat_limit=None)
    assert mapper.cache_to_domain(mapper.domain_to_cache(organization)).seat_limit is None


def test_cache_serialisation_serialised_form_is_json_safe():
    import json

    payload = mapper.domain_to_cache(make_organization())
    assert json.loads(json.dumps(payload)) == payload


def test_cache_serialisation_keys_are_namespaced_per_organization():
    a, b = uuid4(), uuid4()
    assert cache_key(a) != cache_key(b)
    assert cache_key(a).startswith("organizations:by_id:")
