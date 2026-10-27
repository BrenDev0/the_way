"""An organization's provider keys in the real database: one per provider, shared by everyone
in the organization, and gone when the organization is."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.api_keys.domain import ApiKeyCreate, Provider
from src.api_keys.sqlalchemy import adapter as api_keys_adapter
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.staff.domain import StaffMemberCreate
from src.staff.sqlalchemy import adapter as staff_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter


async def make_member(db_session, organization_id):
    return await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=organization_id,
            encrypted_email=f"enc::{uuid4()}@example.com",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::secret",
            role=Role.MEMBER,
        ),
    )


@pytest.fixture
async def tenant(db_session):
    organization = await organizations_adapter.create(db_session, OrganizationCreate(name="Acme Inc"))
    user = await make_member(db_session, organization.id)
    await db_session.commit()
    return organization, user


def build(organization_id, **overrides):
    payload = {
        "organization_id": organization_id,
        "provider": Provider.ANTHROPIC,
        "encrypted_secret": "enc::sk-ant-first",
        "last_four": "irst",
    }
    payload.update(overrides)
    return ApiKeyCreate(**payload)


async def test_setting_a_key_again_replaces_the_row_instead_of_adding_one(db_session, tenant):
    organization, user = tenant

    first = await api_keys_adapter.upsert(db_session, build(organization.id))
    second = await api_keys_adapter.upsert(
        db_session,
        build(organization.id, encrypted_secret="enc::sk-ant-second", last_four="cond"),
    )
    await db_session.commit()

    held = await api_keys_adapter.list_for_user(db_session, user.id)

    assert len(held) == 1
    assert second.id == first.id
    assert second.created_at == first.created_at
    assert held[0].encrypted_secret == "enc::sk-ant-second"
    assert held[0].last_four == "cond"


async def test_an_organization_holds_one_key_per_provider(db_session, tenant):
    organization, user = tenant

    await api_keys_adapter.upsert(db_session, build(organization.id))
    await api_keys_adapter.upsert(
        db_session,
        build(
            organization.id,
            provider=Provider.GOHIGHLEVEL,
            encrypted_secret="enc::pit",
            encrypted_account_id="enc::loc-1",
        ),
    )
    await db_session.commit()

    held = await api_keys_adapter.list_for_user(db_session, user.id)

    assert {key.provider for key in held} == {Provider.ANTHROPIC, Provider.GOHIGHLEVEL}


async def test_every_member_works_through_the_same_keys(db_session, tenant):
    organization, user = tenant
    other = await make_member(db_session, organization.id)
    await api_keys_adapter.upsert(db_session, build(organization.id))
    await db_session.commit()

    mine = await api_keys_adapter.list_for_user(db_session, user.id)
    theirs = await api_keys_adapter.list_for_user(db_session, other.id)

    assert [key.id for key in mine] == [key.id for key in theirs]
    assert len(mine) == 1


async def test_a_user_of_another_organization_gets_none_of_them(db_session, tenant):
    organization, _ = tenant
    elsewhere = await organizations_adapter.create(db_session, OrganizationCreate(name="Other Inc"))
    outsider = await make_member(db_session, elsewhere.id)
    await api_keys_adapter.upsert(db_session, build(organization.id))
    await db_session.commit()

    assert await api_keys_adapter.list_for_user(db_session, outsider.id) == []
    assert await api_keys_adapter.list_for_organization(db_session, elsewhere.id) == []


async def test_another_organization_cannot_delete_the_key(db_session, tenant):
    organization, user = tenant
    await api_keys_adapter.upsert(db_session, build(organization.id))
    await db_session.commit()

    deleted = await api_keys_adapter.delete_for_organization(db_session, uuid4(), Provider.ANTHROPIC)

    assert deleted is False
    assert len(await api_keys_adapter.list_for_user(db_session, user.id)) == 1


async def test_deleting_removes_only_that_provider(db_session, tenant):
    organization, user = tenant
    await api_keys_adapter.upsert(db_session, build(organization.id))
    await api_keys_adapter.upsert(db_session, build(organization.id, provider=Provider.OPENAI))
    await db_session.commit()

    deleted = await api_keys_adapter.delete_for_organization(db_session, organization.id, Provider.ANTHROPIC)
    await db_session.commit()

    assert deleted is True
    assert [key.provider for key in await api_keys_adapter.list_for_user(db_session, user.id)] == [Provider.OPENAI]


async def test_removing_a_user_leaves_the_organizations_keys_alone(db_session, tenant):
    organization, user = tenant
    await api_keys_adapter.upsert(db_session, build(organization.id))
    await db_session.commit()

    await users_adapter.delete_user(db_session, user.id)
    await db_session.commit()

    assert len(await api_keys_adapter.list_for_organization(db_session, organization.id)) == 1


async def test_deleting_the_organization_takes_its_keys_with_it(db_session, tenant):
    organization, _ = tenant
    await api_keys_adapter.upsert(db_session, build(organization.id))
    await db_session.commit()

    await organizations_adapter.delete_by_id(db_session, organization.id)
    await db_session.commit()

    assert await api_keys_adapter.list_for_organization(db_session, organization.id) == []


async def test_removing_the_staff_member_who_set_a_key_keeps_the_key(db_session, tenant):
    organization, user = tenant
    staff = await staff_adapter.create_member(
        db_session,
        StaffMemberCreate(
            encrypted_email="enc::ana@xplorers.example",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::x",
        ),
    )
    await api_keys_adapter.upsert(db_session, build(organization.id, set_by=staff.id))
    await db_session.commit()
    assert (await api_keys_adapter.list_for_user(db_session, user.id))[0].set_by == staff.id

    from sqlalchemy import delete

    from src.staff.sqlalchemy.models import StaffMemberRow

    await db_session.execute(delete(StaffMemberRow).where(StaffMemberRow.id == staff.id))
    await db_session.commit()

    held = await api_keys_adapter.list_for_user(db_session, user.id)
    assert len(held) == 1
    assert held[0].set_by is None
    assert held[0].updated_at <= datetime.now(UTC)
