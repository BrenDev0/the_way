"""Owner invitations end to end: the real app, Postgres and Redis, over HTTP, signed as the
front end signs -- staff sign in, invite an owner, the owner accepts, and the organization
and its owner come to exist. Nothing else creates an organization."""

import json
import re
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.core.communications.domain import Email
from src.core.database.sqlalchemy.core import async_session_factory
from src.core.settings.api import settings as api_settings
from src.fastapi import signing
from src.fastapi.main import app
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.staff.domain import StaffMemberCreate
from src.staff.sqlalchemy import adapter as staff_adapter
from src.users.domain import Role

PASSWORD = "Sup3rSecret!pass"
WEB = "/api/v1"
ACCEPT_URL = "https://staff.example.com/accept-owner-invite"


class RecordingSender:
    def __init__(self) -> None:
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        self.sent.append(email)

    def token_in_last_email(self) -> str:
        match = re.search(r"token=([A-Za-z0-9_-]+)", self.sent[-1].html_body)
        assert match, "the email carries no link with a token"
        return match.group(1)


@pytest.fixture(scope="module")
def client():
    from src.core.database.sqlalchemy.core import engine

    with TestClient(app) as test_client:
        yield test_client
        test_client.portal.call(engine.dispose)


@pytest.fixture(autouse=True)
def dispose_shared_engine():
    """Replaces the package-wide fixture: the app here runs on the test client's loop."""
    yield


@pytest.fixture
def sender(client, monkeypatch):
    recording = RecordingSender()
    monkeypatch.setattr(app.state, "email_sender", recording)
    monkeypatch.setattr(api_settings, "OWNER_INVITATION_ACCEPT_URL", ACCEPT_URL)
    return recording


def signed(method, path, body=b""):
    timestamp = str(int(time.time()))
    return {
        signing.SIGNATURE_HEADER: signing.build_signature(method, path, timestamp, body),
        signing.TIMESTAMP_HEADER: timestamp,
    }


def call(client, method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else b""
    headers = signed(method, path, body)
    if payload is not None:
        headers["Content-Type"] = "application/json"
    return client.request(method, path, content=body or None, headers=headers)


@pytest.fixture
def staff_address(client):
    address = f"staff-{uuid4().hex[:8]}@xplorers.example"
    hashing = app.state.hashing_service
    encryption = app.state.encryption_service

    async def seed():
        async with async_session_factory() as session:
            await staff_adapter.create_member(
                session,
                StaffMemberCreate(
                    encrypted_email=encryption.encrypt(address),
                    email_hash=hashing.deterministic_hash(address),
                    password_hash=hashing.hash_password(PASSWORD),
                ),
            )
            await session.commit()

    client.portal.call(seed)
    return address


def sign_in_staff(client, address, password=PASSWORD):
    client.cookies.clear()
    return call(client, "POST", f"{WEB}/staff/auth/login", {"email": address, "password": password})


@pytest.fixture
def staff(client, staff_address):
    response = sign_in_staff(client, staff_address)
    assert response.status_code == 200, response.text
    return staff_address


def invite(client, **overrides):
    payload = {
        "organizationName": "Acme Inc",
        "email": f"owner-{uuid4().hex[:8]}@acme.example",
        **overrides,
    }
    return call(client, "POST", f"{WEB}/staff/owner-invitations", payload)


def accept(client, token, password=PASSWORD):
    client.cookies.clear()
    return call(client, "POST", f"{WEB}/owner-invitations/accept", {"token": token, "password": password})


# --- staff sign-in --------------------------------------------------------------------


def test_staff_sign_in_with_a_cookie_of_their_own(client, staff_address):
    response = sign_in_staff(client, staff_address)

    assert response.status_code == 200, response.text
    assert response.json()["email"] == staff_address
    assert "staff_session" in client.cookies
    assert "session" not in client.cookies


def test_staff_know_who_they_are_once_signed_in(client, staff):
    response = call(client, "GET", f"{WEB}/staff/auth/me")

    assert response.status_code == 200
    assert response.json()["email"] == staff


def test_a_wrong_password_and_an_unknown_email_get_the_same_answer(client, staff_address):
    wrong = sign_in_staff(client, staff_address, password="not-the-password")
    unknown = sign_in_staff(client, "nobody@xplorers.example")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert "staff_session" not in client.cookies


def test_signing_out_ends_the_session(client, staff):
    assert call(client, "POST", f"{WEB}/staff/auth/logout").status_code == 200

    assert call(client, "GET", f"{WEB}/staff/auth/me").status_code == 401


def test_the_staff_routes_need_a_staff_session(client, sender):
    client.cookies.clear()

    assert call(client, "GET", f"{WEB}/staff/owner-invitations").status_code == 401
    assert invite(client).status_code == 401
    assert sender.sent == []


def test_a_customer_session_is_not_a_staff_session(client, sender, staff):
    """An owner signed in to the panel carries a `session` cookie; the staff routes read
    `staff_session`, so the customer's cookie opens nothing there."""
    token = client.cookies["staff_session"]
    client.cookies.clear()
    client.cookies.set("session", token)

    assert call(client, "GET", f"{WEB}/staff/auth/me").status_code == 401
    assert invite(client).status_code == 401


def test_a_staff_session_is_not_a_customer_session(client, staff):
    token = client.cookies["staff_session"]
    client.cookies.clear()
    client.cookies.set("session", token)

    assert call(client, "GET", f"{WEB}/users/me").status_code == 401


# --- self-registration is closed -------------------------------------------------------


@pytest.mark.parametrize("path", ["/auth/register", "/auth/register/request-verification"])
def test_nobody_can_register_themselves(client, path):
    client.cookies.clear()

    response = call(client, "POST", f"{WEB}{path}", {"email": "x@example.com", "password": PASSWORD})

    assert response.status_code in (404, 405)


# --- the invitation, start to finish ---------------------------------------------------


def test_an_owner_invitation_makes_the_organization_and_its_owner_when_accepted(client, sender, staff):
    address = f"owner-{uuid4().hex[:8]}@acme.example"

    created = invite(client, organizationName="Acme Inc", email=address, seatLimit=7)

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "pending"
    assert body["email"] == address
    assert body["organizationName"] == "Acme Inc"
    assert body["seatLimit"] == 7
    assert body["organizationId"] is None
    assert "token" not in json.dumps(body).lower()
    assert [email.recipient for email in sender.sent] == [address]

    # nothing exists yet but the invitation
    listed = call(client, "GET", f"{WEB}/staff/owner-invitations").json()
    assert [item["status"] for item in listed if item["email"] == address] == ["pending"]

    accepted = accept(client, sender.token_in_last_email())

    assert accepted.status_code == 201, accepted.text
    user = accepted.json()
    assert user["email"] == address
    assert user["role"] == "owner"

    # the new owner signs in with the password they chose
    signed_in = call(client, "POST", f"{WEB}/auth/login", {"email": address, "password": PASSWORD})
    assert signed_in.status_code == 200, signed_in.text
    assert signed_in.json()["user"]["role"] == "owner"

    # and the organization exists, with the seats we set
    async def organization():
        async with async_session_factory() as session:
            return await organizations_adapter.get_by_id(session, user["organizationId"])

    created_organization = client.portal.call(organization)
    assert created_organization.name == "Acme Inc"
    assert created_organization.seat_limit == 7

    # we see it as accepted, pointing at the organization it created
    sign_in_staff(client, staff)
    after = call(client, "GET", f"{WEB}/staff/owner-invitations").json()
    mine = [item for item in after if item["email"] == address]
    assert [(item["status"], item["organizationId"]) for item in mine] == [
        ("accepted", user["organizationId"])
    ]


def test_a_link_works_once(client, sender, staff):
    assert invite(client).status_code == 201
    token = sender.token_in_last_email()

    assert accept(client, token).status_code == 201
    again = accept(client, token)

    assert again.status_code == 409
    assert again.json()["code"] == "invitation_already_accepted"


def test_a_revoked_invitation_cannot_be_accepted(client, sender, staff):
    created = invite(client).json()
    token = sender.token_in_last_email()

    revoked = call(client, "DELETE", f"{WEB}/staff/owner-invitations/{created['id']}")

    assert revoked.status_code == 200
    refused = accept(client, token)
    assert refused.status_code == 404
    assert refused.json()["code"] == "invitation_invalid"


def test_inviting_the_same_address_again_replaces_the_first_link(client, sender, staff):
    address = f"owner-{uuid4().hex[:8]}@acme.example"
    assert invite(client, email=address).status_code == 201
    first = sender.token_in_last_email()
    assert invite(client, email=address, organizationName="Acme Two").status_code == 201
    second = sender.token_in_last_email()

    assert accept(client, first).status_code == 404
    accepted = accept(client, second)
    assert accepted.status_code == 201, accepted.text

    sign_in_staff(client, staff)
    statuses = sorted(
        item["status"] for item in call(client, "GET", f"{WEB}/staff/owner-invitations").json() if item["email"] == address
    )
    assert statuses == ["accepted", "revoked"]


def test_an_unknown_token_is_not_valid(client, sender):
    refused = accept(client, "not-a-real-token")

    assert refused.status_code == 404
    assert refused.json()["code"] == "invitation_invalid"


def test_an_address_that_already_has_an_account_cannot_be_invited(client, sender, staff):
    address = f"owner-{uuid4().hex[:8]}@acme.example"
    assert invite(client, email=address).status_code == 201
    assert accept(client, sender.token_in_last_email()).status_code == 201
    sign_in_staff(client, staff)
    sent_before = len(sender.sent)

    again = invite(client, email=address)

    assert again.status_code == 409
    assert again.json()["code"] == "user_email_already_exists"
    assert len(sender.sent) == sent_before


def test_bad_input_is_refused_and_nothing_is_sent(client, sender, staff):
    for overrides, code in (
        ({"organizationName": "  "}, "organization_name_required"),
        ({"seatLimit": 0}, "seat_limit_invalid"),
        ({"email": "no-at-sign"}, "invitation_email_invalid"),
    ):
        response = invite(client, **overrides)

        assert response.status_code == 422, (overrides, response.text)
        assert response.json()["code"] == code

    assert sender.sent == []


def test_an_owner_made_this_way_can_invite_their_own_people(client, sender, staff, monkeypatch):
    """The member invitation flow is untouched: the new owner invites an admin as before."""
    monkeypatch.setattr(api_settings, "INVITATION_ACCEPT_URL", "https://app.example.com/accept-invite")
    address = f"owner-{uuid4().hex[:8]}@acme.example"
    assert invite(client, email=address).status_code == 201
    assert accept(client, sender.token_in_last_email()).status_code == 201
    assert call(client, "POST", f"{WEB}/auth/login", {"email": address, "password": PASSWORD}).status_code == 200

    response = call(
        client,
        "POST",
        f"{WEB}/invitations",
        {"email": f"admin-{uuid4().hex[:8]}@acme.example", "role": Role.ADMIN.value},
    )

    assert response.status_code == 201, response.text


def test_an_invitation_whose_organization_was_deleted_says_so_and_can_then_be_removed(client, sender, staff):
    address = f"gone-{uuid4().hex[:8]}@acme.example"
    invite(client, organizationName="Short Lived Inc", email=address)
    organization_id = accept(client, sender.token_in_last_email()).json()["organizationId"]
    sign_in_staff(client, staff)

    def mine():
        listed = call(client, "GET", f"{WEB}/staff/owner-invitations").json()
        return next(item for item in listed if item["email"] == address)

    # while the organization exists, the record of how it began cannot be removed
    assert mine()["status"] == "accepted"
    refused = call(client, "DELETE", f"{WEB}/staff/owner-invitations/{mine()['id']}/record")
    assert refused.status_code == 409
    assert refused.json()["code"] == "owner_invitation_in_use"

    deleted = call(
        client,
        "DELETE",
        f"{WEB}/staff/organizations/{organization_id}",
        {"confirmation": "Short Lived Inc"},
    )
    assert deleted.status_code == 200, deleted.text

    # the invitation stays as a record, and now says what became of the organization
    assert mine()["status"] == "organization_deleted"
    assert mine()["organizationId"] is None

    removed = call(client, "DELETE", f"{WEB}/staff/owner-invitations/{mine()['id']}/record")

    assert removed.status_code == 200, removed.text
    assert [item for item in call(client, "GET", f"{WEB}/staff/owner-invitations").json() if item["email"] == address] == []
    assert call(client, "DELETE", f"{WEB}/staff/owner-invitations/{uuid4()}/record").status_code == 404


def test_a_pending_invitation_cannot_be_deleted_only_revoked(client, sender, staff):
    address = f"pending-{uuid4().hex[:8]}@acme.example"
    created = invite(client, organizationName="Acme", email=address).json()

    refused = call(client, "DELETE", f"{WEB}/staff/owner-invitations/{created['id']}/record")

    assert refused.status_code == 409
    assert call(client, "DELETE", f"{WEB}/staff/owner-invitations/{created['id']}").status_code == 200
    # revoked, it can be taken off the list
    assert call(client, "DELETE", f"{WEB}/staff/owner-invitations/{created['id']}/record").status_code == 200


def test_removing_an_invitation_needs_a_staff_session(client, sender):
    client.cookies.clear()

    assert call(client, "DELETE", f"{WEB}/staff/owner-invitations/{uuid4()}/record").status_code == 401
