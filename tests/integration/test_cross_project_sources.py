"""A background worker saves only in its task folder in '.the_way', but works from the
user's files everywhere else -- named project:<name>/<path> -- and a revision it delivers
replaces the file it revises."""

import io
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from helpers import FakeBucketStore
from PIL import Image

from src.background import use_cases as background_use_cases
from src.background.domain import BackgroundTask, TaskStatus
from src.core.exceptions import NotFoundError
from src.media import tools as media_tools
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.projects.files import ProjectFiles
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter


async def make_user(db_session):
    organization = await organizations_adapter.create(db_session, OrganizationCreate(name="Acme"))
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
    await db_session.commit()
    return user


def png(color: str, size: tuple[int, int] = (40, 20)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
async def setup(db_session):
    user = await make_user(db_session)
    bucket = FakeBucketStore()
    files = ProjectFiles(db_session, user.organization_id, user.id, bucket)
    drafts = await files.create_project("Borradores")
    workspace = await files.create_project(".the_way")
    original = await files.write(drafts, "capibara/capibara.png", png("red"), content_type="image/png")
    await db_session.commit()
    return files, drafts, workspace, original, bucket


def context(db_session, files, bucket):
    class Context:
        session = db_session
        organization_id = files._organization_id
        user_id = files._user_id
        bucket_store = bucket

    return Context()


async def test_a_source_in_another_project_is_read_from_there(setup):
    files, drafts, workspace, _, _ = setup

    found, inner = await files.source(workspace, "project:borradores/capibara/capibara.png")

    assert (found.id, inner) == (drafts.id, "capibara/capibara.png")
    assert await files.source(workspace, "tasks/t/a.png") == (workspace, "tasks/t/a.png")
    with pytest.raises(NotFoundError):
        await files.source(workspace, "project:Nope/a.png")
    assert "Nope" not in [p.name for p in await files.projects()]


async def test_a_worker_transforms_the_users_image_into_its_task_folder(db_session, setup):
    files, drafts, workspace, original, bucket = setup
    tools = media_tools.build(context(db_session, files, bucket))  # type: ignore[arg-type]

    result = await tools["TransformImage"].handler(
        project=".the_way", path="project:Borradores/capibara/capibara.png", width=20,
    )

    assert "Saved .the_way/capibara/capibara-editado.png" in result
    _, made = await files.read_bytes(workspace, "capibara/capibara-editado.png")
    assert Image.open(io.BytesIO(made)).size == (20, 10)
    # the original is untouched
    _, kept = await files.read_bytes(drafts, "capibara/capibara.png")
    assert kept == png("red")
    inspected = await tools["InspectImage"].handler(project=".the_way", path="project:Borradores/capibara/capibara.png")
    assert inspected.startswith("Borradores/capibara/capibara.png: 40x20 px")


async def test_a_delivered_revision_replaces_the_file_it_revises(db_session, setup):
    files, drafts, workspace, original, _ = setup
    task = BackgroundTask(
        id=uuid4(), organization_id=files._organization_id, user_id=files._user_id,
        conversation_id=None, description="Gorra", instructions="", folder="gorra",
        deliver_project="Borradores", deliver_path="capibara", status=TaskStatus.DONE,
        result=None, reported=False, created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    await files.write(workspace, "tasks/gorra/capibara.png", png("blue"), content_type="image/png")

    report = await background_use_cases.deliver(files, task, "Borradores", "capibara")

    assert "Delivered to Borradores/capibara" in report
    replaced = await files.file(drafts, "capibara/capibara.png")
    assert replaced.id == original.id  # pages linking to it now show the revision
    _, content = await files.read_bytes(drafts, "capibara/capibara.png")
    assert content == png("blue")


async def test_copying_still_refuses_to_overwrite(setup):
    files, drafts, workspace, _, _ = setup
    await files.write(workspace, "capibara.png", png("blue"), content_type="image/png")

    with pytest.raises(Exception, match="already in the destination"):
        await files.copy(workspace, "capibara.png", drafts, "capibara")
