from uuid import uuid4

import pytest

from src.api_keys.domain import ApiKeyCreate, Provider
from src.api_keys.sqlalchemy import adapter as api_keys_adapter
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
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
    organization = await organizations_adapter.create(
        db_session, OrganizationCreate(name="Acme Inc")
    )
    user = await make_member(db_session, organization.id)
    await db_session.commit()
    return organization, user


def build(organization_id, user_id, **overrides):
    payload = {
        "organization_id": organization_id,
        "user_id": user_id,
        "provider": Provider.ANTHROPIC,
        "encrypted_secret": "enc::sk-ant-first",
        "last_four": "irst",
    }
    payload.update(overrides)
    return ApiKeyCreate(**payload)


async def test_reissuing_replaces_the_row_instead_of_adding_one(db_session, tenant):
    organization, user = tenant

    first = await api_keys_adapter.upsert(db_session, build(organization.id, user.id))
    second = await api_keys_adapter.upsert(
        db_session,
        build(organization.id, user.id, encrypted_secret="enc::sk-ant-second", last_four="cond"),
    )
    await db_session.commit()

    held = await api_keys_adapter.list_for_user(db_session, user.id)

    assert len(held) == 1
    assert second.id == first.id
    assert second.created_at == first.created_at
    assert held[0].encrypted_secret == "enc::sk-ant-second"
    assert held[0].last_four == "cond"


async def test_a_user_can_hold_one_key_per_provider(db_session, tenant):
    organization, user = tenant

    await api_keys_adapter.upsert(db_session, build(organization.id, user.id))
    await api_keys_adapter.upsert(
        db_session,
        build(
            organization.id,
            user.id,
            provider=Provider.GOHIGHLEVEL,
            encrypted_secret="enc::pit",
            encrypted_account_id="enc::loc-1",
        ),
    )
    await db_session.commit()

    held = await api_keys_adapter.list_for_user(db_session, user.id)

    assert {key.provider for key in held} == {Provider.ANTHROPIC, Provider.GOHIGHLEVEL}


async def test_another_organization_cannot_see_the_key(db_session, tenant):
    organization, user = tenant
    await api_keys_adapter.upsert(db_session, build(organization.id, user.id))
    await db_session.commit()

    visible = await api_keys_adapter.list_for_organization(db_session, uuid4())

    assert visible == []


async def test_another_organization_cannot_delete_the_key(db_session, tenant):
    organization, user = tenant
    api_key = await api_keys_adapter.upsert(db_session, build(organization.id, user.id))
    await db_session.commit()

    deleted = await api_keys_adapter.delete_for_organization(
        db_session, api_key.id, uuid4()
    )

    assert deleted is False
    assert len(await api_keys_adapter.list_for_user(db_session, user.id)) == 1


async def test_the_owning_organization_can_delete_the_key(db_session, tenant):
    organization, user = tenant
    api_key = await api_keys_adapter.upsert(db_session, build(organization.id, user.id))
    await db_session.commit()

    deleted = await api_keys_adapter.delete_for_organization(
        db_session, api_key.id, organization.id
    )

    assert deleted is True
    assert await api_keys_adapter.list_for_user(db_session, user.id) == []


async def test_listing_can_be_narrowed_to_one_user(db_session, tenant):
    organization, user = tenant
    other = await make_member(db_session, organization.id)
    await db_session.commit()

    await api_keys_adapter.upsert(db_session, build(organization.id, user.id))
    await api_keys_adapter.upsert(db_session, build(organization.id, other.id))
    await db_session.commit()

    assert len(await api_keys_adapter.list_for_organization(db_session, organization.id)) == 2
    narrowed = await api_keys_adapter.list_for_organization(
        db_session, organization.id, user.id
    )
    assert [key.user_id for key in narrowed] == [user.id]


async def test_deleting_the_user_takes_their_keys_with_them(db_session, tenant):
    organization, user = tenant
    await api_keys_adapter.upsert(db_session, build(organization.id, user.id))
    await db_session.commit()

    await users_adapter.delete_user(db_session, user.id)
    await db_session.commit()

    assert await api_keys_adapter.list_for_organization(db_session, organization.id) == []


async def test_deleting_the_issuing_admin_leaves_the_key_in_place(db_session, tenant):
    organization, user = tenant
    admin = await make_member(db_session, organization.id)
    await db_session.commit()

    await api_keys_adapter.upsert(
        db_session, build(organization.id, user.id, issued_by=admin.id)
    )
    await db_session.commit()

    await users_adapter.delete_user(db_session, admin.id)
    await db_session.commit()

    held = await api_keys_adapter.list_for_user(db_session, user.id)

    assert len(held) == 1
    assert held[0].issued_by is None
