from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from helpers import make_organization, make_user

from src.core.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from src.invitations import use_cases as invitations_use_cases
from src.invitations.domain import Invitation
from src.users.domain import Role

ACCEPT_URL = "https://app.example.com/accept-invite"


def make_invitation(
    *,
    organization_id=None,
    email="new@example.com",
    role: Role = Role.MEMBER,
    expires_in: timedelta = timedelta(days=7),
    accepted_at=None,
    revoked_at=None,
) -> Invitation:
    now = datetime.now(UTC)
    return Invitation(
        id=uuid4(),
        organization_id=organization_id or uuid4(),
        encrypted_email=f"enc::{email}",
        email_hash=f"dhash::{email}",
        role=role,
        expires_at=now + expires_in,
        accepted_at=accepted_at,
        revoked_at=revoked_at,
        invited_by=uuid4(),
        created_at=now,
        updated_at=now,
    )


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent = []

    async def send(self, email) -> None:
        self.sent.append(email)


@pytest.mark.parametrize("role", [Role.ADMIN, Role.MEMBER])
def test_an_owner_may_invite_admins_and_members(role):
    invitations_use_cases.assert_may_invite(Role.OWNER, role)


def test_an_admin_may_invite_a_member():
    invitations_use_cases.assert_may_invite(Role.ADMIN, Role.MEMBER)


def test_an_admin_may_not_invite_another_admin():
    with pytest.raises(AuthorizationError) as exc:
        invitations_use_cases.assert_may_invite(Role.ADMIN, Role.ADMIN)

    assert exc.value.code == "invitation_role_not_allowed"
    assert exc.value.status_code == 403


@pytest.mark.parametrize("inviter", [Role.OWNER, Role.ADMIN])
def test_nobody_may_invite_an_owner(inviter):
    with pytest.raises(AuthorizationError) as exc:
        invitations_use_cases.assert_may_invite(inviter, Role.OWNER)

    assert exc.value.code == "invitation_role_not_allowed"


@pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN, Role.MEMBER])
def test_a_member_may_not_invite_anyone(role):
    with pytest.raises(AuthorizationError):
        invitations_use_cases.assert_may_invite(Role.MEMBER, role)


def test_an_unlimited_organization_never_runs_out_of_seats():
    invitations_use_cases.assert_seat_available(
        make_organization(seat_limit=None), members=500, pending=500
    )


def test_seats_are_available_below_the_limit():
    invitations_use_cases.assert_seat_available(
        make_organization(seat_limit=5), members=3, pending=1
    )


def test_pending_invitations_consume_seats():
    with pytest.raises(ConflictError) as exc:
        invitations_use_cases.assert_seat_available(
            make_organization(seat_limit=5), members=3, pending=2
        )

    assert exc.value.code == "organization_seat_limit_reached"
    assert exc.value.status_code == 409


def test_a_full_organization_is_refused():
    with pytest.raises(ConflictError):
        invitations_use_cases.assert_seat_available(
            make_organization(seat_limit=1), members=1, pending=0
        )


@pytest.fixture
def invite(hashing_service, encryption_service):
    created = []
    revoked = []
    sender = FakeEmailSender()

    async def run(
        inviter_role: Role = Role.OWNER,
        role: Role = Role.MEMBER,
        existing_user=None,
        members: int = 1,
        pending: int = 0,
        seat_limit: int | None = None,
    ):
        organization = make_organization(seat_limit=seat_limit)

        async def get_user_by_email_hash_fn(_email_hash):
            return existing_user

        async def count_users_for_organization_fn(_organization_id):
            return members

        async def count_pending_for_organization_fn(_organization_id):
            return pending

        async def revoke_pending_for_email_fn(organization_id, email_hash):
            revoked.append((organization_id, email_hash))
            return 0

        async def create_invitation_fn(invitation):
            created.append(invitation)
            return make_invitation(
                organization_id=invitation.organization_id, role=invitation.role
            )

        return await invitations_use_cases.invite_user(
            organization=organization,
            inviter=make_user(role=inviter_role, organization_id=organization.id),
            email="new@example.com",
            role=role,
            get_user_by_email_hash_fn=get_user_by_email_hash_fn,
            count_users_for_organization_fn=count_users_for_organization_fn,
            count_pending_for_organization_fn=count_pending_for_organization_fn,
            revoke_pending_for_email_fn=revoke_pending_for_email_fn,
            create_invitation_fn=create_invitation_fn,
            email_sender=sender,
            hashing_service=hashing_service,
            encryption_service=encryption_service,
            accept_url=ACCEPT_URL,
        )

    run.created = created
    run.revoked = revoked
    run.sender = sender
    return run


async def test_the_email_is_stored_encrypted_and_hashed(invite):
    await invite()

    assert invite.created[0].encrypted_email == "enc::new@example.com"
    assert invite.created[0].email_hash == "dhash::new@example.com"


async def test_the_invited_role_is_recorded(invite):
    await invite(role=Role.ADMIN)

    assert invite.created[0].role is Role.ADMIN


async def test_only_a_hash_of_the_token_is_stored(invite):
    await invite()

    assert invite.created[0].token_hash.startswith("dhash::")


async def test_an_invitation_email_is_sent_with_a_link(invite):
    await invite()

    assert len(invite.sender.sent) == 1
    assert ACCEPT_URL + "?token=" in invite.sender.sent[0].html_body


async def test_the_raw_token_never_leaves_the_email(invite):
    invitation = await invite()

    assert not hasattr(invitation, "token")
    assert "token_hash" not in vars(invitation)


async def test_an_admin_inviting_an_admin_is_refused(invite):
    with pytest.raises(AuthorizationError):
        await invite(inviter_role=Role.ADMIN, role=Role.ADMIN)

    assert invite.created == []


async def test_inviting_an_existing_account_is_a_conflict(invite):
    with pytest.raises(ConflictError) as exc:
        await invite(existing_user=make_user())

    assert exc.value.code == "user_email_already_exists"
    assert invite.sender.sent == []


async def test_a_full_organization_cannot_invite(invite):
    with pytest.raises(ConflictError) as exc:
        await invite(members=2, pending=1, seat_limit=3)

    assert exc.value.code == "organization_seat_limit_reached"
    assert invite.created == []


async def test_re_inviting_supersedes_the_earlier_invitation(invite):
    await invite()

    assert len(invite.revoked) == 1
    assert invite.revoked[0][1] == "dhash::new@example.com"


@pytest.fixture
def resolve(hashing_service):
    async def run(invitation):
        async def get_invitation_by_token_hash_fn(_token_hash):
            return invitation

        return await invitations_use_cases.resolve_invitation(
            token="raw-token",
            get_invitation_by_token_hash_fn=get_invitation_by_token_hash_fn,
            hashing_service=hashing_service,
        )

    return run


async def test_a_pending_invitation_resolves(resolve):
    invitation = make_invitation()

    assert (await resolve(invitation)).id == invitation.id


async def test_an_unknown_token_is_rejected(resolve):
    with pytest.raises(NotFoundError) as exc:
        await resolve(None)

    assert exc.value.code == "invitation_invalid"


async def test_an_accepted_invitation_cannot_be_reused(resolve):
    with pytest.raises(ConflictError) as exc:
        await resolve(make_invitation(accepted_at=datetime.now(UTC)))

    assert exc.value.code == "invitation_already_accepted"


async def test_a_revoked_invitation_is_rejected(resolve):
    with pytest.raises(NotFoundError) as exc:
        await resolve(make_invitation(revoked_at=datetime.now(UTC)))

    assert exc.value.code == "invitation_invalid"


async def test_an_expired_invitation_is_rejected(resolve):
    with pytest.raises(ValidationError) as exc:
        await resolve(make_invitation(expires_in=timedelta(seconds=-1)))

    assert exc.value.code == "invitation_expired"


@pytest.fixture
def accept(hashing_service):
    created = []
    accepted = []

    async def run(
        invitation=None,
        existing_user=None,
        members: int = 1,
        pending: int = 1,
        seat_limit: int | None = None,
    ):
        organization = make_organization(seat_limit=seat_limit)
        target = invitation or make_invitation(
            organization_id=organization.id, role=Role.ADMIN
        )

        async def get_user_by_email_hash_fn(_email_hash):
            return existing_user

        async def count_users_for_organization_fn(_organization_id):
            return members

        async def count_pending_for_organization_fn(_organization_id):
            return pending

        async def create_user_fn(user):
            created.append(user)
            return make_user(
                organization_id=user.organization_id,
                encrypted_email=user.encrypted_email,
                email_hash=user.email_hash,
                password_hash=user.password_hash,
                role=user.role,
            )

        async def accept_invitation_fn(invitation_id):
            accepted.append(invitation_id)
            return target

        return await invitations_use_cases.accept_invitation(
            token="raw-token",
            password="Sup3rSecret!",
            organization=organization,
            invitation=target,
            get_user_by_email_hash_fn=get_user_by_email_hash_fn,
            count_users_for_organization_fn=count_users_for_organization_fn,
            count_pending_for_organization_fn=count_pending_for_organization_fn,
            create_user_fn=create_user_fn,
            accept_invitation_fn=accept_invitation_fn,
            hashing_service=hashing_service,
        )

    run.created = created
    run.accepted = accepted
    return run


async def test_accepting_creates_the_user_with_the_invited_role(accept):
    user = await accept()

    assert user.role is Role.ADMIN


async def test_the_new_user_joins_the_inviting_organization(accept):
    invitation = make_invitation()

    user = await accept(invitation=invitation)

    assert user.organization_id == invitation.organization_id


async def test_the_email_comes_from_the_invitation_not_the_request(accept):
    await accept()

    assert accept.created[0].encrypted_email == "enc::new@example.com"


async def test_the_password_is_hashed(accept):
    await accept()

    assert accept.created[0].password_hash == "pwhash::Sup3rSecret!"


async def test_the_invitation_is_marked_accepted(accept):
    invitation = make_invitation()

    await accept(invitation=invitation)

    assert accept.accepted == [invitation.id]


async def test_accepting_when_the_email_was_taken_meanwhile_is_a_conflict(accept):
    with pytest.raises(ConflictError) as exc:
        await accept(existing_user=make_user())

    assert exc.value.code == "user_email_already_exists"
    assert accept.created == []


async def test_the_accepting_invitation_does_not_count_against_its_own_seat(accept):
    user = await accept(members=2, pending=1, seat_limit=3)

    assert user is not None


async def test_accepting_into_a_full_organization_is_refused(accept):
    with pytest.raises(ConflictError) as exc:
        await accept(members=3, pending=1, seat_limit=3)

    assert exc.value.code == "organization_seat_limit_reached"
