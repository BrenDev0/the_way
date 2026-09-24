from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.invitations.domain import InvitationCreate
from src.invitations.sqlalchemy import adapter as invitations_adapter
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter


async def make_org(db_session, name="Acme Inc"):
    organization = await organizations_adapter.create(
        db_session, OrganizationCreate(name=name)
    )
    user = await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=organization.id,
            encrypted_email=f"enc::{uuid4()}@example.com",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::secret",
            role=Role.OWNER,
        ),
    )
    return organization, user


@pytest.fixture
async def tenant(db_session):
    organization, user = await make_org(db_session)
    await db_session.commit()
    return organization, user


def invitation_for(organization, user, **overrides):
    payload = {
        "organization_id": organization.id,
        "encrypted_email": "enc::new@example.com",
        "email_hash": f"dhash::{uuid4()}",
        "role": Role.MEMBER,
        "token_hash": f"tokenhash-{uuid4()}",
        "expires_at": datetime.now(UTC) + timedelta(days=7),
        "invited_by": user.id,
    }
    payload.update(overrides)
    return InvitationCreate(**payload)


async def test_an_invitation_round_trips(db_session, tenant):
    organization, user = tenant
    await invitations_adapter.create(
        db_session, invitation_for(organization, user, role=Role.ADMIN)
    )
    await db_session.commit()

    listed = await invitations_adapter.list_pending_for_organization(
        db_session, organization.id
    )

    assert len(listed) == 1
    assert listed[0].role is Role.ADMIN
    assert listed[0].encrypted_email == "enc::new@example.com"


async def test_lookup_by_token_hash_finds_it(db_session, tenant):
    organization, user = tenant
    payload = invitation_for(organization, user)
    await invitations_adapter.create(db_session, payload)
    await db_session.commit()

    found = await invitations_adapter.get_by_token_hash(db_session, payload.token_hash)

    assert found is not None
    assert found.organization_id == organization.id


async def test_an_unknown_token_finds_nothing(db_session, tenant):
    assert await invitations_adapter.get_by_token_hash(db_session, "nope") is None


async def test_the_response_shape_never_carries_the_token(db_session, tenant):
    organization, user = tenant
    created = await invitations_adapter.create(
        db_session, invitation_for(organization, user)
    )
    await db_session.commit()

    assert not hasattr(created, "token_hash")


async def test_an_accepted_invitation_leaves_the_pending_list(db_session, tenant):
    organization, user = tenant
    created = await invitations_adapter.create(
        db_session, invitation_for(organization, user)
    )
    await invitations_adapter.accept(db_session, created.id)
    await db_session.commit()

    assert await invitations_adapter.list_pending_for_organization(
        db_session, organization.id
    ) == []


async def test_a_revoked_invitation_leaves_the_pending_list(db_session, tenant):
    organization, user = tenant
    created = await invitations_adapter.create(
        db_session, invitation_for(organization, user)
    )
    await invitations_adapter.revoke(db_session, created.id, organization.id)
    await db_session.commit()

    assert await invitations_adapter.count_pending_for_organization(
        db_session, organization.id
    ) == 0


async def test_an_expired_invitation_leaves_the_pending_list(db_session, tenant):
    organization, user = tenant
    await invitations_adapter.create(
        db_session,
        invitation_for(
            organization, user, expires_at=datetime.now(UTC) - timedelta(seconds=1)
        ),
    )
    await db_session.commit()

    assert await invitations_adapter.count_pending_for_organization(
        db_session, organization.id
    ) == 0


async def test_another_organization_cannot_revoke_it(db_session, tenant):
    organization, user = tenant
    created = await invitations_adapter.create(
        db_session, invitation_for(organization, user)
    )
    await db_session.commit()

    assert await invitations_adapter.revoke(db_session, created.id, uuid4()) is False
    assert await invitations_adapter.count_pending_for_organization(
        db_session, organization.id
    ) == 1


async def test_an_accepted_invitation_cannot_be_revoked(db_session, tenant):
    organization, user = tenant
    created = await invitations_adapter.create(
        db_session, invitation_for(organization, user)
    )
    await invitations_adapter.accept(db_session, created.id)
    await db_session.commit()

    assert await invitations_adapter.revoke(db_session, created.id, organization.id) is False


async def test_another_organization_sees_no_invitations(db_session, tenant):
    organization, user = tenant
    await invitations_adapter.create(db_session, invitation_for(organization, user))
    await db_session.commit()

    assert await invitations_adapter.list_pending_for_organization(
        db_session, uuid4()
    ) == []


async def test_re_inviting_revokes_the_earlier_one(db_session, tenant):
    organization, user = tenant
    email_hash = f"dhash::{uuid4()}"
    await invitations_adapter.create(
        db_session, invitation_for(organization, user, email_hash=email_hash)
    )
    await db_session.commit()

    revoked = await invitations_adapter.revoke_pending_for_email(
        db_session, organization.id, email_hash
    )
    await invitations_adapter.create(
        db_session, invitation_for(organization, user, email_hash=email_hash)
    )
    await db_session.commit()

    assert revoked == 1
    assert await invitations_adapter.count_pending_for_organization(
        db_session, organization.id
    ) == 1


async def test_a_pending_invitation_is_found_by_email(db_session, tenant):
    organization, user = tenant
    email_hash = f"dhash::{uuid4()}"
    await invitations_adapter.create(
        db_session, invitation_for(organization, user, email_hash=email_hash)
    )
    await db_session.commit()

    found = await invitations_adapter.get_pending_for_email(
        db_session, organization.id, email_hash
    )

    assert found is not None


async def test_deleting_the_organization_takes_its_invitations(db_session, tenant):
    organization, user = tenant
    await invitations_adapter.create(db_session, invitation_for(organization, user))
    await db_session.commit()

    await organizations_adapter.delete_by_id(db_session, organization.id)
    await db_session.commit()

    assert await invitations_adapter.count_pending_for_organization(
        db_session, organization.id
    ) == 0


async def test_deleting_the_inviter_leaves_the_invitation(db_session, tenant):
    organization, _user = tenant
    other = await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=organization.id,
            encrypted_email=f"enc::{uuid4()}@example.com",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::secret",
            role=Role.ADMIN,
        ),
    )
    await db_session.commit()
    await invitations_adapter.create(
        db_session, invitation_for(organization, other)
    )
    await db_session.commit()

    await users_adapter.delete_user(db_session, other.id)
    await db_session.commit()

    listed = await invitations_adapter.list_pending_for_organization(
        db_session, organization.id
    )
    assert len(listed) == 1
    assert listed[0].invited_by is None


async def test_the_seat_count_is_scoped_to_one_organization(db_session, tenant):
    organization, _user = tenant
    other, _other_user = await make_org(db_session, name="Rival Ltd")
    await db_session.commit()

    assert await users_adapter.count_for_organization(db_session, organization.id) == 1
    assert await users_adapter.count_for_organization(db_session, other.id) == 1
