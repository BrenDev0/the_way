"""Staff seeing every organization and deleting one, end to end: the real app, Postgres,
Redis and an S3 bucket (MinIO), over HTTP, signed and signed in as the dashboard does.

The delete is the point: it must remove the organization, its people and exactly its own
files, ask for the exact name first, and leave every other organization untouched."""

import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.core.database.sqlalchemy.core import async_session_factory
from src.documents import keys as document_keys
from src.fastapi import signing
from src.fastapi.main import app
from src.invitations.domain import InvitationCreate
from src.invitations.sqlalchemy import adapter as invitations_adapter
from src.organizations import keys as organization_keys
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.projects import keys as project_keys
from src.projects.domain import FileStatus
from src.projects.sqlalchemy.models import FileRow, ProjectRow
from src.sessions.domain import SessionCreate
from src.sessions.sqlalchemy import adapter as sessions_adapter
from src.staff.domain import StaffMemberCreate
from src.staff.sqlalchemy import adapter as staff_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

PASSWORD = "Sup3rSecret!pass"
WEB = "/api/v1"


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
def staff(client):
    """A staff member, signed in."""
    address = f"staff-{uuid4().hex[:8]}@xplorers.example"
    hashing, encryption = app.state.hashing_service, app.state.encryption_service

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
    client.cookies.clear()
    assert call(client, "POST", f"{WEB}/staff/auth/login", {"email": address, "password": PASSWORD}).status_code == 200
    return address


def put_object(client, key, tmp_path):
    source = tmp_path / "object.bin"
    source.write_bytes(b"x" * 64)

    async def put():
        await app.state.bucket_store.put(key, source)

    client.portal.call(put)


def stored_under(client, prefix):
    async def listing():
        return [item.key for item in await app.state.bucket_store.list(prefix)]

    return client.portal.call(listing)


@pytest.fixture
def organization(client, tmp_path):
    """An organization with an owner, an admin and a member (all able to sign in), an open
    invitation, a project with two finished files, and objects in the bucket."""
    encryption, hashing = app.state.encryption_service, app.state.hashing_service
    name = f"Acme {uuid4().hex[:6]}"
    emails = {role: f"{role.value}-{uuid4().hex[:6]}@acme.example" for role in (Role.OWNER, Role.ADMIN, Role.MEMBER)}
    found: dict = {"name": name, "emails": emails}

    async def seed():
        async with async_session_factory() as session:
            created = await organizations_adapter.create(session, OrganizationCreate(name=name, seat_limit=5))
            found["id"] = created.id
            await session.commit()
            for role, address in emails.items():
                user = await users_adapter.create(
                    session,
                    UserCreate(
                        organization_id=created.id,
                        encrypted_email=encryption.encrypt(address),
                        email_hash=hashing.deterministic_hash(address),
                        password_hash=hashing.hash_password(PASSWORD),
                        role=role,
                    ),
                )
                await session.commit()
                if role is Role.OWNER:
                    found["owner_id"] = user.id
                    now = datetime.now(UTC)
                    await sessions_adapter.create(
                        session,
                        SessionCreate(
                            user_id=user.id, token_hash=f"hash-{uuid4()}", expires_at=now + timedelta(days=1), last_seen_at=now
                        ),
                    )
                    await session.commit()
            await invitations_adapter.create(
                session,
                InvitationCreate(
                    organization_id=created.id,
                    encrypted_email=encryption.encrypt("pending@acme.example"),
                    email_hash=hashing.deterministic_hash("pending@acme.example"),
                    role=Role.MEMBER,
                    token_hash=f"tokenhash-{uuid4()}",
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                ),
            )
            project = ProjectRow(organization_id=created.id, owner_id=found["owner_id"], name="docs")
            session.add(project)
            await session.flush()
            for size in (1_000, 2_000):
                session.add(
                    FileRow(project_id=project.id, name=f"f{size}", content_type="text/plain", size_bytes=size, status=FileStatus.READY.value)
                )
            await session.commit()

    client.portal.call(seed)
    found["keys"] = [
        project_keys.file_key(found["id"], uuid4()),
        project_keys.file_key(found["id"], uuid4()),
        document_keys.document_key(found["id"], uuid4(), "manual.pdf"),
    ]
    for key in found["keys"]:
        put_object(client, key, tmp_path)
    return found


def list_organizations(client):
    response = call(client, "GET", f"{WEB}/staff/organizations")
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()}


# --- who may ask --------------------------------------------------------------------------------


def test_every_staff_organization_route_needs_a_staff_session(client, organization):
    client.cookies.clear()
    path = f"{WEB}/staff/organizations"

    assert call(client, "GET", path).status_code == 401
    assert call(client, "GET", f"{path}/deleted").status_code == 401
    assert call(client, "GET", f"{path}/{organization['id']}").status_code == 401
    assert call(client, "DELETE", f"{path}/{organization['id']}", {"confirmation": organization["name"]}).status_code == 401
    # and nothing was touched
    assert len(stored_under(client, organization_keys.organization_prefix(organization["id"]))) == 3


def test_a_customer_signed_in_to_the_panel_is_not_staff(client, organization):
    client.cookies.clear()
    owner = organization["emails"][Role.OWNER]
    assert call(client, "POST", f"{WEB}/auth/login", {"email": owner, "password": PASSWORD}).status_code == 200

    assert call(client, "GET", f"{WEB}/staff/organizations").status_code == 401
    assert call(client, "DELETE", f"{WEB}/staff/organizations/{organization['id']}", {"confirmation": organization["name"]}).status_code == 401
    # the customer's own panel session did not delete anything either
    assert len(stored_under(client, organization_keys.organization_prefix(organization["id"]))) == 3
    client.cookies.clear()


# --- reading ----------------------------------------------------------------------------------------


def test_staff_see_every_organization_with_its_owner_and_its_counts(client, staff, organization):
    found = list_organizations(client)[str(organization["id"])]

    assert found["name"] == organization["name"]
    assert found["ownerEmail"] == organization["emails"][Role.OWNER]
    assert found["seatLimit"] == 5
    assert (found["members"], found["pendingInvitations"]) == (3, 1)
    assert (found["files"], found["bytes"]) == (2, 3_000)
    assert found["lastSeenAt"] is not None


def test_staff_see_an_organizations_people_and_open_invitations(client, staff, organization):
    response = call(client, "GET", f"{WEB}/staff/organizations/{organization['id']}")

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["organization"]["name"] == organization["name"]
    assert [(m["email"], m["role"]) for m in detail["members"]] == [
        (organization["emails"][Role.OWNER], "owner"),
        (organization["emails"][Role.ADMIN], "admin"),
        (organization["emails"][Role.MEMBER], "member"),
    ]
    assert detail["members"][0]["lastSeenAt"] is not None
    assert detail["members"][2]["lastSeenAt"] is None
    assert [i["email"] for i in detail["pendingInvitations"]] == ["pending@acme.example"]


def test_what_staff_see_holds_no_secret_and_no_content(client, staff, organization):
    body = call(client, "GET", f"{WEB}/staff/organizations/{organization['id']}").text.lower()

    for forbidden in ("password", "tokenhash", "token_hash", "content", "apikey", "api_key"):
        assert forbidden not in body


def test_an_unknown_organization_is_a_404_and_a_malformed_id_is_a_422(client, staff):
    assert call(client, "GET", f"{WEB}/staff/organizations/{uuid4()}").status_code == 404
    assert call(client, "GET", f"{WEB}/staff/organizations/not-an-id").status_code == 422
    assert call(client, "DELETE", f"{WEB}/staff/organizations/{uuid4()}", {"confirmation": "x"}).status_code == 404


# --- deleting ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("typed", ["", "acme", "wrong name"])
def test_a_wrong_name_deletes_nothing(client, staff, organization, typed):
    response = call(client, "DELETE", f"{WEB}/staff/organizations/{organization['id']}", {"confirmation": typed})

    assert response.status_code == 422
    assert response.json()["code"] == "confirmation_mismatch"
    assert str(organization["id"]) in list_organizations(client)
    assert len(stored_under(client, organization_keys.organization_prefix(organization["id"]))) == 3
    records = call(client, "GET", f"{WEB}/staff/organizations/deleted").json()
    assert all(record["organizationId"] != str(organization["id"]) for record in records)  # no record: nothing was deleted


def test_deleting_with_the_exact_name_removes_the_organization_its_people_and_its_files(client, staff, organization):
    response = call(
        client, "DELETE", f"{WEB}/staff/organizations/{organization['id']}", {"confirmation": organization["name"]}
    )

    assert response.status_code == 200, response.text
    record = response.json()
    assert record["organizationName"] == organization["name"]
    assert record["organizationId"] == str(organization["id"])
    assert record["deletedByEmail"] == staff
    assert (record["members"], record["files"], record["bytes"]) == (3, 2, 3_000)
    assert (record["filesRemoved"], record["filesLeft"]) == (3, 0)

    # the organization is gone, as is everything it had
    assert str(organization["id"]) not in list_organizations(client)
    assert call(client, "GET", f"{WEB}/staff/organizations/{organization['id']}").status_code == 404
    assert stored_under(client, organization_keys.organization_prefix(organization["id"])) == []


def test_the_people_of_a_deleted_organization_can_no_longer_sign_in(client, staff, organization):
    owner = organization["emails"][Role.OWNER]
    client.cookies.clear()
    assert call(client, "POST", f"{WEB}/auth/login", {"email": owner, "password": PASSWORD}).status_code == 200

    # back to staff to delete the organization, then the owner tries again
    client.cookies.clear()
    assert call(client, "POST", f"{WEB}/staff/auth/login", {"email": staff, "password": PASSWORD}).status_code == 200
    assert call(client, "DELETE", f"{WEB}/staff/organizations/{organization['id']}", {"confirmation": organization["name"]}).status_code == 200

    client.cookies.clear()
    refused = call(client, "POST", f"{WEB}/auth/login", {"email": owner, "password": PASSWORD})
    assert refused.status_code == 401
    assert refused.json()["code"] == "invalid_credentials"


def test_deleting_one_organization_leaves_every_other_one_and_its_files_untouched(client, staff, organization, tmp_path):
    other_name = f"Other {uuid4().hex[:6]}"
    encryption, hashing = app.state.encryption_service, app.state.hashing_service
    other_email = f"owner-{uuid4().hex[:6]}@other.example"
    other = {}

    async def seed():
        async with async_session_factory() as session:
            created = await organizations_adapter.create(session, OrganizationCreate(name=other_name))
            other["id"] = created.id
            await session.commit()
            await users_adapter.create(
                session,
                UserCreate(
                    organization_id=created.id,
                    encrypted_email=encryption.encrypt(other_email),
                    email_hash=hashing.deterministic_hash(other_email),
                    password_hash=hashing.hash_password(PASSWORD),
                    role=Role.OWNER,
                ),
            )
            await session.commit()

    client.portal.call(seed)
    other_keys = [project_keys.file_key(other["id"], uuid4()), document_keys.document_key(other["id"], uuid4(), "b.pdf")]
    for key in other_keys:
        put_object(client, key, tmp_path)

    response = call(client, "DELETE", f"{WEB}/staff/organizations/{organization['id']}", {"confirmation": organization["name"]})

    assert response.status_code == 200
    assert str(other["id"]) in list_organizations(client)
    assert sorted(stored_under(client, organization_keys.organization_prefix(other["id"]))) == sorted(other_keys)
    client.cookies.clear()
    assert call(client, "POST", f"{WEB}/auth/login", {"email": other_email, "password": PASSWORD}).status_code == 200


def test_a_deletion_stays_on_record_with_who_did_it_and_what_it_was(client, staff, organization):
    call(client, "DELETE", f"{WEB}/staff/organizations/{organization['id']}", {"confirmation": organization["name"]})

    records = call(client, "GET", f"{WEB}/staff/organizations/deleted")

    assert records.status_code == 200
    mine = [r for r in records.json() if r["organizationId"] == str(organization["id"])]
    assert len(mine) == 1
    assert mine[0]["organizationName"] == organization["name"]
    assert mine[0]["deletedByEmail"] == staff
    assert (mine[0]["members"], mine[0]["files"], mine[0]["filesLeft"]) == (3, 2, 0)


def test_deleting_the_same_organization_twice_is_a_404_the_second_time(client, staff, organization):
    path = f"{WEB}/staff/organizations/{organization['id']}"
    assert call(client, "DELETE", path, {"confirmation": organization["name"]}).status_code == 200

    again = call(client, "DELETE", path, {"confirmation": organization["name"]})

    assert again.status_code == 404
    records = [r for r in call(client, "GET", f"{WEB}/staff/organizations/deleted").json() if r["organizationId"] == str(organization["id"])]
    assert len(records) == 1  # one deletion, one record


# --- a damaged record must not hide the rest ---------------------------------------------------


@pytest.fixture
def damaged_organization(client):
    """An organization whose owner email no longer decrypts (a restore, a rotated key, a bad
    edit): the stored text is not a valid token."""
    found = {"name": f"Damaged {uuid4().hex[:6]}"}

    async def seed():
        async with async_session_factory() as session:
            created = await organizations_adapter.create(session, OrganizationCreate(name=found["name"]))
            found["id"] = created.id
            await session.commit()
            await users_adapter.create(
                session,
                UserCreate(
                    organization_id=created.id,
                    encrypted_email="enc::this-is-not-a-fernet-token",
                    email_hash=f"dhash::{uuid4()}",
                    password_hash="pwhash::x",
                    role=Role.OWNER,
                ),
            )
            await session.commit()

    client.portal.call(seed)
    return found


def test_one_damaged_record_does_not_break_the_list_and_shows_as_damaged(client, staff, organization, damaged_organization):
    listed = list_organizations(client)

    assert listed[str(organization["id"])]["ownerEmail"] == organization["emails"][Role.OWNER]  # the others are fine
    assert listed[str(damaged_organization["id"])]["ownerEmail"] == "(no se pudo leer)"


def test_a_damaged_organization_can_still_be_opened(client, staff, damaged_organization):
    detail_id = damaged_organization["id"]
    response = call(client, "GET", f"{WEB}/staff/organizations/{detail_id}")

    assert response.status_code == 200, response.text
    assert [m["email"] for m in response.json()["members"]] == ["(no se pudo leer)"]


def test_a_damaged_organization_can_still_be_deleted(client, staff, damaged_organization):
    """The point of a staff tool: the broken one is exactly the one that has to go."""
    organization_id = damaged_organization["id"]
    path = f"{WEB}/staff/organizations/{organization_id}"

    assert call(client, "DELETE", path, {"confirmation": damaged_organization["name"]}).status_code == 200
    assert call(client, "GET", path).status_code == 404


# --- the edges of what can be typed ---------------------------------------------------------------------


def test_an_organization_with_a_one_letter_name_can_be_deleted(client, staff):
    """The API asks every string for two characters; the confirmation is exempt, or an
    organization named 'Z' could never be deleted."""
    seeded = {}

    async def seed():
        async with async_session_factory() as session:
            created = await organizations_adapter.create(session, OrganizationCreate(name="Z"))
            seeded["id"] = created.id
            await session.commit()

    client.portal.call(seed)
    path = f"{WEB}/staff/organizations/{seeded['id']}"

    assert call(client, "DELETE", path, {"confirmation": "Y"}).json()["code"] == "confirmation_mismatch"
    assert call(client, "DELETE", path, {"confirmation": ""}).json()["code"] == "confirmation_mismatch"
    assert call(client, "DELETE", path, {"confirmation": "Z"}).status_code == 200
    assert call(client, "GET", path).status_code == 404


def test_a_staff_member_whose_password_is_one_character_can_sign_in(client):
    """python -m src.staff.create takes any non-empty password; the sign-in has to accept
    what it makes."""
    address = f"short-{uuid4().hex[:8]}@xplorers.example"
    hashing, encryption = app.state.hashing_service, app.state.encryption_service

    async def seed():
        async with async_session_factory() as session:
            await staff_adapter.create_member(
                session,
                StaffMemberCreate(
                    encrypted_email=encryption.encrypt(address),
                    email_hash=hashing.deterministic_hash(address),
                    password_hash=hashing.hash_password("a"),
                ),
            )
            await session.commit()

    client.portal.call(seed)
    client.cookies.clear()

    assert call(client, "POST", f"{WEB}/staff/auth/login", {"email": address, "password": "a"}).status_code == 200
    assert call(client, "GET", f"{WEB}/staff/organizations").status_code == 200
    client.cookies.clear()
    assert call(client, "POST", f"{WEB}/staff/auth/login", {"email": address, "password": "b"}).status_code == 401
