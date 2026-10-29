from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from helpers import make_organization, make_user

from src.core.communications.domain import Email
from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.organizations.domain import OrganizationCreate
from src.staff.domain import (
    OwnerInvitation,
    OwnerInvitationCreate,
    OwnerInvitationStatus,
    StaffMember,
    status_of,
)
from src.staff.use_cases import owner_invitations as use_cases
from src.users.domain import Role, UserCreate

ACCEPT_URL = "https://staff.example.com/accept-owner-invite"
EMAIL = "founder@acme.example"


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        self.sent.append(email)


def make_staff() -> StaffMember:
    return StaffMember(
        id=uuid4(),
        encrypted_email="enc::staff@xplorers.example",
        email_hash="dhash::staff@xplorers.example",
        password_hash="pwhash::secret",
        created_at=datetime.now(UTC),
    )


def make_invitation(
    *,
    email: str = EMAIL,
    organization_name: str = "Acme Inc",
    seat_limit: int | None = None,
    expires_in: timedelta = timedelta(days=7),
    accepted_at=None,
    revoked_at=None,
    organization_id=None,
) -> OwnerInvitation:
    now = datetime.now(UTC)
    return OwnerInvitation(
        id=uuid4(),
        organization_name=organization_name,
        encrypted_email=f"enc::{email}",
        email_hash=f"dhash::{email}",
        seat_limit=seat_limit,
        expires_at=now + expires_in,
        accepted_at=accepted_at,
        revoked_at=revoked_at,
        invited_by=uuid4(),
        organization_id=organization_id,
        created_at=now,
        updated_at=now,
    )


async def no_user(email_hash: str):
    return None


async def existing_user(email_hash: str):
    return make_user()


@pytest.fixture
def sender():
    return FakeEmailSender()


@pytest.fixture
def created():
    return []


@pytest.fixture
def revoked_for():
    return []


@pytest.fixture
def invite(created, revoked_for, sender, hashing_service, encryption_service):
    async def create(payload: OwnerInvitationCreate):
        created.append(payload)
        now = datetime.now(UTC)
        return OwnerInvitation(
            id=uuid4(),
            organization_name=payload.organization_name,
            encrypted_email=payload.encrypted_email,
            email_hash=payload.email_hash,
            seat_limit=payload.seat_limit,
            expires_at=payload.expires_at,
            accepted_at=None,
            revoked_at=None,
            invited_by=payload.invited_by,
            organization_id=None,
            created_at=now,
            updated_at=now,
        )

    async def revoke_pending(email_hash: str) -> int:
        revoked_for.append(email_hash)
        return 0

    async def run(
        organization_name="Acme Inc",
        email=EMAIL,
        seat_limit=None,
        get_user_by_email_hash_fn=no_user,
        staff=None,
    ):
        return await use_cases.invite_owner(
            staff=staff or make_staff(),
            organization_name=organization_name,
            email=email,
            seat_limit=seat_limit,
            get_user_by_email_hash_fn=get_user_by_email_hash_fn,
            revoke_pending_for_email_fn=revoke_pending,
            create_owner_invitation_fn=create,
            email_sender=sender,
            hashing_service=hashing_service,
            encryption_service=encryption_service,
            accept_url=ACCEPT_URL,
        )

    return run


async def test_inviting_an_owner_emails_the_invitee_a_link_with_the_token(invite, sender, created, hashing_service):
    await invite()

    assert len(sender.sent) == 1
    assert sender.sent[0].recipient == EMAIL
    link_start = sender.sent[0].html_body.index(ACCEPT_URL + "?token=") + len(ACCEPT_URL + "?token=")
    token = sender.sent[0].html_body[link_start:].split('"')[0].split("<")[0]
    assert hashing_service.deterministic_hash(token) == created[0].token_hash


async def test_the_token_itself_is_never_stored(invite, created):
    await invite()

    assert created[0].token_hash.startswith("dhash::")
    assert "token=" not in created[0].token_hash


async def test_the_invitation_records_who_sent_it_and_stores_the_email_encrypted(invite, created):
    staff = make_staff()

    await invite(staff=staff)

    assert created[0].invited_by == staff.id
    assert created[0].encrypted_email == f"enc::{EMAIL}"
    assert created[0].email_hash == f"dhash::{EMAIL}"


async def test_the_name_is_tidied_and_the_seat_limit_kept(invite, created):
    await invite(organization_name="  Acme   Inc \n", seat_limit=5)

    assert created[0].organization_name == "Acme Inc"
    assert created[0].seat_limit == 5


async def test_the_link_expires(invite, created):
    await invite()

    assert created[0].expires_at > datetime.now(UTC) + timedelta(days=6)


async def test_inviting_an_address_again_revokes_the_earlier_link(invite, revoked_for):
    await invite()

    assert revoked_for == [f"dhash::{EMAIL}"]


async def test_an_address_that_already_has_an_account_is_refused_before_anything_is_sent(
    invite, sender, created
):
    with pytest.raises(ConflictError) as exc:
        await invite(get_user_by_email_hash_fn=existing_user)

    assert exc.value.code == "user_email_already_exists"
    assert sender.sent == []
    assert created == []


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"organization_name": "   "}, "organization_name_required"),
        ({"organization_name": "x" * 256}, "organization_name_too_long"),
        ({"seat_limit": 0}, "seat_limit_invalid"),
        ({"email": "not-an-email"}, "invitation_email_invalid"),
    ],
)
async def test_bad_input_is_refused_before_anything_is_sent(invite, sender, created, overrides, code):
    with pytest.raises(ValidationError) as exc:
        await invite(**overrides)

    assert exc.value.code == code
    assert sender.sent == []
    assert created == []


async def test_an_organization_name_is_text_in_the_email_never_markup(invite, sender):
    await invite(organization_name='<img src=x onerror="steal()">')

    assert "<img" not in sender.sent[0].html_body
    assert "&lt;img" in sender.sent[0].html_body


# --- resolving the link ---------------------------------------------------------------


async def resolve(invitation, hashing_service):
    async def get_by_token_hash(token_hash: str):
        return invitation

    return await use_cases.resolve_owner_invitation(
        token="raw-token",
        get_owner_invitation_by_token_hash_fn=get_by_token_hash,
        hashing_service=hashing_service,
    )


async def test_a_valid_link_resolves(hashing_service):
    invitation = make_invitation()

    assert await resolve(invitation, hashing_service) is invitation


async def test_an_unknown_link_is_not_valid(hashing_service):
    with pytest.raises(NotFoundError) as exc:
        await resolve(None, hashing_service)

    assert exc.value.code == "invitation_invalid"


async def test_a_used_link_says_so(hashing_service):
    with pytest.raises(ConflictError) as exc:
        await resolve(make_invitation(accepted_at=datetime.now(UTC)), hashing_service)

    assert exc.value.code == "invitation_already_accepted"


async def test_a_revoked_link_looks_like_an_unknown_one(hashing_service):
    with pytest.raises(NotFoundError) as exc:
        await resolve(make_invitation(revoked_at=datetime.now(UTC)), hashing_service)

    assert exc.value.code == "invitation_invalid"


async def test_a_lapsed_link_asks_for_a_new_one(hashing_service):
    with pytest.raises(ValidationError) as exc:
        await resolve(make_invitation(expires_in=timedelta(seconds=-1)), hashing_service)

    assert exc.value.code == "invitation_expired"


# --- accepting ------------------------------------------------------------------------


@pytest.fixture
def accept(hashing_service):
    state = {"orgs": [], "users": [], "claims": []}

    async def create_org(organization: OrganizationCreate):
        state["orgs"].append(organization)
        return make_organization(name=organization.name, seat_limit=organization.seat_limit)

    async def create_user(user: UserCreate):
        state["users"].append(user)
        return make_user(
            organization_id=user.organization_id,
            encrypted_email=user.encrypted_email,
            email_hash=user.email_hash,
            password_hash=user.password_hash,
            role=user.role,
        )

    async def run(invitation, password="Sup3rSecret!pass", get_user=no_user, claim_wins=True):
        async def claim(invitation_id, organization_id):
            state["claims"].append((invitation_id, organization_id))
            return claim_wins

        return await use_cases.accept_owner_invitation(
            invitation=invitation,
            password=password,
            get_user_by_email_hash_fn=get_user,
            create_organization_fn=create_org,
            claim_owner_invitation_fn=claim,
            create_user_fn=create_user,
            hashing_service=hashing_service,
        )

    run.state = state
    return run


async def test_accepting_creates_the_organization_and_its_owner(accept):
    invitation = make_invitation(organization_name="Acme Inc", seat_limit=8)

    organization, user = await accept(invitation)

    assert [(o.name, o.seat_limit) for o in accept.state["orgs"]] == [("Acme Inc", 8)]
    assert user.organization_id == organization.id
    assert user.role is Role.OWNER


async def test_the_owner_gets_the_invited_email_and_a_hashed_password(accept, hashing_service):
    invitation = make_invitation()

    _, user = await accept(invitation, password="Sup3rSecret!pass")

    assert user.encrypted_email == invitation.encrypted_email
    assert user.email_hash == invitation.email_hash
    assert user.password_hash == hashing_service.hash_password("Sup3rSecret!pass")
    assert user.password_hash != "Sup3rSecret!pass"


async def test_the_invitation_is_claimed_for_the_organization_it_created(accept):
    invitation = make_invitation()

    organization, _ = await accept(invitation)

    assert accept.state["claims"] == [(invitation.id, organization.id)]


async def test_losing_the_race_for_a_link_creates_no_owner(accept):
    with pytest.raises(ConflictError) as exc:
        await accept(make_invitation(), claim_wins=False)

    assert exc.value.code == "invitation_already_accepted"
    assert accept.state["users"] == []


async def test_an_address_that_got_an_account_since_is_refused_before_anything_is_created(accept):
    with pytest.raises(ConflictError) as exc:
        await accept(make_invitation(), get_user=existing_user)

    assert exc.value.code == "user_email_already_exists"
    assert accept.state["orgs"] == []
    assert accept.state["claims"] == []


# --- revoking and status --------------------------------------------------------------


async def test_revoking_an_unknown_invitation_is_not_found():
    async def revoke(invitation_id):
        return False

    with pytest.raises(NotFoundError) as exc:
        await use_cases.revoke_owner_invitation(uuid4(), revoke)

    assert exc.value.code == "invitation_not_found"


def test_status_reads_the_invitation_as_it_stands():
    now = datetime.now(UTC)

    assert status_of(make_invitation(), now) is OwnerInvitationStatus.PENDING
    assert status_of(make_invitation(expires_in=timedelta(days=-1)), now) is OwnerInvitationStatus.EXPIRED
    assert status_of(make_invitation(revoked_at=now), now) is OwnerInvitationStatus.REVOKED
    assert status_of(make_invitation(accepted_at=now, organization_id=uuid4()), now) is OwnerInvitationStatus.ACCEPTED


def test_an_accepted_invitation_stays_accepted_after_its_link_would_have_lapsed():
    now = datetime.now(UTC)
    invitation = make_invitation(expires_in=timedelta(days=-1), accepted_at=now - timedelta(days=3), organization_id=uuid4())

    assert status_of(invitation, now) is OwnerInvitationStatus.ACCEPTED


def test_an_accepted_invitation_whose_organization_was_deleted_says_so():
    now = datetime.now(UTC)
    # accepting fills in the organization; deleting the organization clears it again
    deleted = make_invitation(accepted_at=now - timedelta(days=2), organization_id=None)

    assert status_of(deleted, now) is OwnerInvitationStatus.ORGANIZATION_DELETED


class Records:
    """Invitations held in memory, with the two ports the delete takes."""

    def __init__(self, *invitations: OwnerInvitation) -> None:
        self.held = {invitation.id: invitation for invitation in invitations}

    async def get(self, invitation_id):
        return self.held.get(invitation_id)

    async def delete(self, invitation_id):
        return self.held.pop(invitation_id, None) is not None


@pytest.mark.parametrize(
    "invitation",
    [
        make_invitation(revoked_at=datetime.now(UTC)),
        make_invitation(expires_in=timedelta(days=-1)),
        make_invitation(accepted_at=datetime.now(UTC), organization_id=None),
    ],
    ids=["revoked", "lapsed", "organization-deleted"],
)
async def test_a_finished_invitation_can_be_taken_off_the_list(invitation):
    records = Records(invitation)

    await use_cases.delete_owner_invitation(invitation.id, records.get, records.delete)

    assert records.held == {}


@pytest.mark.parametrize(
    "invitation",
    [make_invitation(), make_invitation(accepted_at=datetime.now(UTC), organization_id=uuid4())],
    ids=["still-usable", "organization-exists"],
)
async def test_an_invitation_still_in_use_cannot_be_deleted(invitation):
    records = Records(invitation)

    with pytest.raises(ConflictError) as exc:
        await use_cases.delete_owner_invitation(invitation.id, records.get, records.delete)

    assert exc.value.code == "owner_invitation_in_use"
    assert exc.value.status_code == 409
    assert invitation.id in records.held


async def test_deleting_an_unknown_invitation_is_not_found():
    records = Records()

    with pytest.raises(NotFoundError) as exc:
        await use_cases.delete_owner_invitation(uuid4(), records.get, records.delete)

    assert exc.value.code == "invitation_not_found"
