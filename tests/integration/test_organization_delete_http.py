"""An owner deleting their own organization, end to end: the real app, Postgres, Redis and an S3
bucket (MinIO). Everything the organization stored goes with it, in the database and in the
bucket, and no other organization loses a thing."""

import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from src.core.database.sqlalchemy.core import async_session_factory
from src.documents import keys as document_keys
from src.fastapi import signing
from src.fastapi.main import app
from src.organizations import keys as organization_keys
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.organizations.sqlalchemy.models import OrganizationRow
from src.projects import keys as project_keys
from src.projects.domain import FileStatus
from src.projects.sqlalchemy.models import FileRow, ProjectRow
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter
from src.users.sqlalchemy.models import UserRow

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


def call(client, method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else b""
    timestamp = str(int(time.time()))
    headers = {
        signing.SIGNATURE_HEADER: signing.build_signature(method, path, timestamp, body),
        signing.TIMESTAMP_HEADER: timestamp,
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    return client.request(method, path, content=body or None, headers=headers)


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


def make_organization(client, tmp_path):
    """An organization with an owner and a member, a project with two files, and objects in the
    bucket: project files and a document."""
    encryption, hashing = app.state.encryption_service, app.state.hashing_service
    found: dict = {"emails": {}}

    async def seed():
        async with async_session_factory() as session:
            created = await organizations_adapter.create(session, OrganizationCreate(name=f"Acme {uuid4().hex[:6]}"))
            found["id"] = created.id
            await session.commit()
            for role in (Role.OWNER, Role.MEMBER):
                address = f"{role.value}-{uuid4().hex[:6]}@acme.example"
                found["emails"][role] = address
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


def rows_left(client, organization_id):
    async def count():
        async with async_session_factory() as session:
            organizations = await session.scalar(select(func.count()).select_from(OrganizationRow).where(OrganizationRow.id == organization_id))
            users = await session.scalar(select(func.count()).select_from(UserRow).where(UserRow.organization_id == organization_id))
            projects = await session.scalar(select(func.count()).select_from(ProjectRow).where(ProjectRow.organization_id == organization_id))
            return organizations, users, projects

    return client.portal.call(count)


def sign_in(client, address):
    client.cookies.clear()
    assert call(client, "POST", f"{WEB}/auth/login", {"email": address, "password": PASSWORD}).status_code == 200


def test_deleting_the_organization_clears_its_rows_and_every_file_it_stored(client, tmp_path):
    organization = make_organization(client, tmp_path)
    prefix = organization_keys.organization_prefix(organization["id"])
    assert len(stored_under(client, prefix)) == 3
    sign_in(client, organization["emails"][Role.OWNER])

    response = call(client, "DELETE", f"{WEB}/organizations/me")

    assert response.status_code == 200, response.text
    assert rows_left(client, organization["id"]) == (0, 0, 0)
    assert stored_under(client, prefix) == []


def test_another_organizations_files_are_untouched(client, tmp_path):
    leaving = make_organization(client, tmp_path)
    staying = make_organization(client, tmp_path)
    sign_in(client, leaving["emails"][Role.OWNER])

    assert call(client, "DELETE", f"{WEB}/organizations/me").status_code == 200

    assert sorted(stored_under(client, organization_keys.organization_prefix(staying["id"]))) == sorted(staying["keys"])
    assert rows_left(client, staying["id"]) == (1, 2, 1)


def test_only_the_owner_can_delete_and_nothing_is_cleared_when_refused(client, tmp_path):
    organization = make_organization(client, tmp_path)
    sign_in(client, organization["emails"][Role.MEMBER])

    response = call(client, "DELETE", f"{WEB}/organizations/me")

    assert response.status_code == 403
    assert len(stored_under(client, organization_keys.organization_prefix(organization["id"]))) == 3
    assert rows_left(client, organization["id"]) == (1, 2, 1)
    client.cookies.clear()


def test_a_bucket_that_fails_does_not_stop_the_organization_being_deleted(client, tmp_path, monkeypatch):
    from src.core.bucket.domain import BucketError

    organization = make_organization(client, tmp_path)
    sign_in(client, organization["emails"][Role.OWNER])

    async def unreachable(_prefix):
        raise BucketError("bucket unreachable")

    monkeypatch.setattr(app.state.bucket_store, "list", unreachable)

    response = call(client, "DELETE", f"{WEB}/organizations/me")

    assert response.status_code == 200, response.text
    assert rows_left(client, organization["id"]) == (0, 0, 0)
    monkeypatch.undo()
    # the files are still there to be cleared later by running the cleanup again
    assert len(stored_under(client, organization_keys.organization_prefix(organization["id"]))) == 3
