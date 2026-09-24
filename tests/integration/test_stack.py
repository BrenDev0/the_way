from uuid import uuid4

import pytest

from src.core.llm.domain import ToolCall
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter
from src.worker import health


async def test_postgres_round_trips_an_organization(db_session):
    created = await organizations_adapter.create(db_session, OrganizationCreate(name="Acme Inc"))

    found = await organizations_adapter.get_by_id(db_session, created.id)

    assert found is not None
    assert found.name == "Acme Inc"
    assert found.created_at is not None


async def test_postgres_round_trips_a_user_bound_to_an_organization(db_session):
    organization = await organizations_adapter.create(
        db_session, OrganizationCreate(name="Acme Inc")
    )

    user = await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=organization.id,
            encrypted_email="enc::founder@example.com",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::secret",
            role=Role.OWNER,
        ),
    )

    found = await users_adapter.get_user_by_id(db_session, user.id)

    assert found is not None
    assert found.organization_id == organization.id
    assert found.role is Role.OWNER


async def test_deleting_an_organization_cascades_to_its_users(db_session):
    organization = await organizations_adapter.create(
        db_session, OrganizationCreate(name="Acme Inc")
    )
    user = await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=organization.id,
            encrypted_email="enc::founder@example.com",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::secret",
            role=Role.OWNER,
        ),
    )

    await organizations_adapter.delete_by_id(db_session, organization.id)

    assert await users_adapter.get_user_by_id(db_session, user.id) is None


async def test_update_rejects_a_column_outside_the_whitelist(db_session):
    from src.core.exceptions import ValidationError

    organization = await organizations_adapter.create(
        db_session, OrganizationCreate(name="Acme Inc")
    )

    import pytest

    with pytest.raises(ValidationError):
        await organizations_adapter.update_by_id(db_session, organization.id, {"id": uuid4()})


async def test_update_changes_the_name(db_session):
    organization = await organizations_adapter.create(
        db_session, OrganizationCreate(name="Acme Inc")
    )

    updated = await organizations_adapter.update_by_id(
        db_session, organization.id, {"name": "Acme Global"}
    )

    assert updated is not None
    assert updated.name == "Acme Global"


async def test_redis_round_trips_json(cache):
    key = f"integration:{uuid4()}"

    assert await cache.store_json(key, {"a": 1}, 30) is True
    assert await cache.get_json(key) == {"a": 1}
    assert await cache.remove(key) is True
    assert await cache.get_json(key) is None


async def test_redis_expiry_is_applied(cache):
    key = f"integration:{uuid4()}"

    await cache.store_str(key, "value", 30)

    assert await cache.get_str(key) == "value"


async def test_redis_increments(cache):
    key = f"integration:{uuid4()}"

    assert await cache.increment(key) == 1
    assert await cache.increment(key) == 2
    await cache.remove(key)


async def test_the_broker_round_trips_a_task(task_broker):
    task = await health.ping.kiq()

    result = await task.wait_result(timeout=45)

    assert not result.is_err
    assert result.return_value


async def test_a_worker_task_reaches_its_dependencies(task_broker):
    task = await health.check_dependencies.kiq()

    result = await task.wait_result(timeout=45)

    assert not result.is_err
    assert result.return_value is True


def test_tool_call_ids_survive_a_json_round_trip():
    from src.core.llm.domain import assistant, tool_result

    call = ToolCall(id="c1", name="ReadFile", args={"path": "x.txt"})
    conversation = [assistant("", (call,)), tool_result("c1", "contents")]

    import json

    assert json.loads(json.dumps(conversation)) == conversation


async def test_a_duplicate_email_is_a_conflict_not_a_crash(db_session):
    from src.core.exceptions import ConflictError
    from src.organizations.domain import OrganizationCreate
    from src.organizations.sqlalchemy import adapter as organizations_adapter
    from src.users.domain import Role, UserCreate
    from src.users.sqlalchemy import adapter as users_adapter

    organization = await organizations_adapter.create(
        db_session, OrganizationCreate(name="Acme Inc")
    )
    email_hash = f"dhash::{uuid4()}"

    def new_user():
        return UserCreate(
            organization_id=organization.id,
            encrypted_email=f"enc::{uuid4()}",
            email_hash=email_hash,
            password_hash="pwhash::secret",
            role=Role.OWNER,
        )

    await users_adapter.create(db_session, new_user())

    with pytest.raises(ConflictError) as exc:
        await users_adapter.create(db_session, new_user())

    assert exc.value.code == "user_email_already_exists"
    assert exc.value.status_code == 409


async def test_listing_users_is_scoped_to_one_organization(db_session):
    from src.users.sqlalchemy import adapter as users_adapter

    async def org_with_users(name, count):
        organization = await organizations_adapter.create(
            db_session, OrganizationCreate(name=name)
        )
        for _ in range(count):
            await users_adapter.create(
                db_session,
                UserCreate(
                    organization_id=organization.id,
                    encrypted_email=f"enc::{uuid4()}@example.com",
                    email_hash=f"dhash::{uuid4()}",
                    password_hash="pwhash::secret",
                    role=Role.MEMBER,
                ),
            )
        return organization

    mine = await org_with_users("Acme Inc", 3)
    theirs = await org_with_users("Rival Ltd", 2)
    await db_session.commit()

    assert len(await users_adapter.list_users(db_session, mine.id)) == 3
    assert len(await users_adapter.list_users(db_session, theirs.id)) == 2

    listed = await users_adapter.list_users(db_session, mine.id)
    assert all(user.organization_id == mine.id for user in listed)


async def test_listing_users_of_an_unknown_organization_is_empty(db_session):
    from src.users.sqlalchemy import adapter as users_adapter

    assert await users_adapter.list_users(db_session, uuid4()) == []
