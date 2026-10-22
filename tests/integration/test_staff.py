"""The staff adapter against real Postgres: the queries behind sign-in and owner
invitations, including the one that decides who gets a link's organization."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.core.cryptography.fernet.adapter import FernetEncryptionService
from src.core.settings.shared import settings
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.staff.domain import (
    OwnerInvitationCreate,
    StaffMemberCreate,
    StaffSessionCreate,
)
from src.staff.sqlalchemy import adapter

ENCRYPTION = FernetEncryptionService(settings.CRYPTOGRAPHY_FERNET_KEY)


@pytest.fixture
async def staff(db_session):
    member = await adapter.create_member(
        db_session,
        StaffMemberCreate(
            encrypted_email=f"enc::{uuid4()}@xplorers.example",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::secret",
        ),
    )
    await db_session.commit()
    return member


@pytest.fixture
async def organization(db_session):
    created = await organizations_adapter.create(db_session, OrganizationCreate(name="Claimed Co", seat_limit=3))
    await db_session.commit()
    return created


def invitation_for(staff, **overrides):
    payload = {
        "organization_name": "Acme Inc",
        # really encrypted: the list route decrypts every row in the shared test database
        "encrypted_email": ENCRYPTION.encrypt("owner@acme.example"),
        "email_hash": f"dhash::{uuid4()}",
        "seat_limit": None,
        "token_hash": f"tokenhash-{uuid4()}",
        "expires_at": datetime.now(UTC) + timedelta(days=7),
        "invited_by": staff.id,
    }
    payload.update(overrides)
    return OwnerInvitationCreate(**payload)


async def test_a_staff_member_is_found_by_email_hash_and_by_id(db_session, staff):
    by_hash = await adapter.get_member_by_email_hash(db_session, staff.email_hash)
    by_id = await adapter.get_member_by_id(db_session, staff.id)

    assert by_hash is not None and by_id is not None
    assert by_hash.id == by_id.id == staff.id
    assert by_hash.password_hash == "pwhash::secret"


async def test_two_staff_members_cannot_share_an_email(db_session, staff):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await adapter.create_member(
            db_session,
            StaffMemberCreate(encrypted_email="x", email_hash=staff.email_hash, password_hash="y"),
        )


async def test_a_session_round_trips_and_can_be_touched_and_revoked(db_session, staff):
    now = datetime.now(UTC)
    created = await adapter.create_session(
        db_session,
        StaffSessionCreate(
            staff_id=staff.id, token_hash=f"hash-{uuid4()}", expires_at=now + timedelta(hours=1), last_seen_at=now
        ),
    )
    await db_session.commit()

    found = await adapter.get_session_by_token_hash(db_session, created.token_hash)
    touched = await adapter.touch_session(db_session, created.id)
    revoked = await adapter.revoke_session_by_token_hash(db_session, created.token_hash)
    after = await adapter.get_session_by_token_hash(db_session, created.token_hash)

    assert found is not None and found.staff_id == staff.id
    assert touched is not None and touched.last_seen_at >= created.last_seen_at
    assert revoked is True
    assert after is not None and after.revoked_at is not None


async def test_an_unknown_session_token_finds_nothing_and_revokes_nothing(db_session):
    assert await adapter.get_session_by_token_hash(db_session, "nope") is None
    assert await adapter.revoke_session_by_token_hash(db_session, "nope") is False


async def test_an_invitation_round_trips_with_no_organization_yet(db_session, staff):
    payload = invitation_for(staff, seat_limit=5)
    created = await adapter.create_invitation(db_session, payload)
    await db_session.commit()

    found = await adapter.get_invitation_by_token_hash(db_session, payload.token_hash)

    assert found is not None
    assert found.id == created.id
    assert (found.organization_name, found.seat_limit) == ("Acme Inc", 5)
    assert found.organization_id is None
    assert found.accepted_at is None
    assert found.invited_by == staff.id


async def test_the_list_holds_every_invitation_newest_first(db_session, staff):
    first = await adapter.create_invitation(db_session, invitation_for(staff))
    await db_session.commit()
    second = await adapter.create_invitation(db_session, invitation_for(staff))
    await db_session.commit()
    await adapter.revoke_invitation(db_session, first.id)
    await db_session.commit()

    listed = [item.id for item in await adapter.list_invitations(db_session)]

    assert listed.index(second.id) < listed.index(first.id)


async def test_an_invitation_can_be_claimed_only_once(db_session, staff, organization):
    created = await adapter.create_invitation(db_session, invitation_for(staff))
    await db_session.commit()

    first = await adapter.claim_invitation(db_session, created.id, organization.id)
    await db_session.commit()
    second = await adapter.claim_invitation(db_session, created.id, organization.id)

    assert first is True
    assert second is False


async def test_a_claimed_invitation_records_the_organization(db_session, staff, organization):
    payload = invitation_for(staff)
    created = await adapter.create_invitation(db_session, payload)
    await db_session.commit()

    await adapter.claim_invitation(db_session, created.id, organization.id)
    await db_session.commit()

    found = await adapter.get_invitation_by_token_hash(db_session, payload.token_hash)
    assert found is not None
    assert found.organization_id == organization.id
    assert found.accepted_at is not None


async def test_a_revoked_invitation_cannot_be_claimed(db_session, staff, organization):
    created = await adapter.create_invitation(db_session, invitation_for(staff))
    await adapter.revoke_invitation(db_session, created.id)
    await db_session.commit()

    assert await adapter.claim_invitation(db_session, created.id, organization.id) is False


async def test_a_lapsed_invitation_cannot_be_claimed(db_session, staff, organization):
    created = await adapter.create_invitation(
        db_session, invitation_for(staff, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()

    assert await adapter.claim_invitation(db_session, created.id, organization.id) is False


async def test_an_accepted_invitation_cannot_be_revoked(db_session, staff, organization):
    created = await adapter.create_invitation(db_session, invitation_for(staff))
    await adapter.claim_invitation(db_session, created.id, organization.id)
    await db_session.commit()

    assert await adapter.revoke_invitation(db_session, created.id) is False


async def test_revoking_an_unknown_invitation_is_false(db_session):
    assert await adapter.revoke_invitation(db_session, uuid4()) is False


async def test_revoking_pending_ones_for_an_address_leaves_other_addresses_alone(db_session, staff):
    address_hash = f"dhash::{uuid4()}"
    mine = await adapter.create_invitation(db_session, invitation_for(staff, email_hash=address_hash))
    other = await adapter.create_invitation(db_session, invitation_for(staff))
    await db_session.commit()

    revoked = await adapter.revoke_pending_invitations_for_email(db_session, address_hash)
    await db_session.commit()

    assert revoked == 1
    by_id = {item.id: item for item in await adapter.list_invitations(db_session)}
    assert by_id[mine.id].revoked_at is not None
    assert by_id[other.id].revoked_at is None


# --- the command that adds the first staff member ---------------------------------------


async def test_the_create_command_adds_a_staff_member_who_can_sign_in(db_session, monkeypatch, capsys):
    from src.core.cryptography.bcrypt.adapter import BcryptHashingService
    from src.staff import create

    address = f"new-{uuid4().hex[:8]}@xplorers.example"
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "a-long-enough-password")

    assert await create.main(["--email", f"  {address}  "]) == 0

    hashing = BcryptHashingService()
    member = await adapter.get_member_by_email_hash(db_session, hashing.deterministic_hash(address))
    assert member is not None
    assert ENCRYPTION.decrypt(member.encrypted_email) == address
    assert hashing.compare_password("a-long-enough-password", member.password_hash)
    assert "created" in capsys.readouterr().out


async def test_the_create_command_refuses_a_password_typed_differently_twice(db_session, monkeypatch, capsys):
    from src.core.cryptography.bcrypt.adapter import BcryptHashingService
    from src.staff import create

    address = f"new-{uuid4().hex[:8]}@xplorers.example"
    answers = iter(["a-long-enough-password", "something-else-entirely"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))

    assert await create.main(["--email", address]) == 1

    member = await adapter.get_member_by_email_hash(db_session, BcryptHashingService().deterministic_hash(address))
    assert member is None
    assert "differ" in capsys.readouterr().err


async def test_the_create_command_refuses_a_short_password_and_a_repeat(db_session, monkeypatch, capsys):
    from src.staff import create

    address = f"new-{uuid4().hex[:8]}@xplorers.example"
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "short")
    assert await create.main(["--email", address]) == 1
    assert "at least" in capsys.readouterr().err

    monkeypatch.setattr("getpass.getpass", lambda prompt="": "a-long-enough-password")
    assert await create.main(["--email", address]) == 0
    capsys.readouterr()
    assert await create.main(["--email", address]) == 1
    assert "already" in capsys.readouterr().err
