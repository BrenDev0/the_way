"""The organization's library: one per organization, every member reads it, only owners
and admins change it (and only through the routes), and no agent ever writes to it."""

import io
from uuid import uuid4

import pytest
from helpers import FakeBucketStore
from PIL import Image

from src.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from src.knowledge.tools import build_context
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.projects import config as projects_config
from src.projects import use_cases
from src.projects.files import ProjectFiles
from src.projects.management import use_cases as management_use_cases
from src.projects.sqlalchemy import adapter as projects_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter

LIBRARY = projects_config.LIBRARY_PROJECT


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(out, format="PNG")
    return out.getvalue()


async def make_user(db_session, organization_id, role):
    return await users_adapter.create(
        db_session,
        UserCreate(
            organization_id=organization_id,
            encrypted_email=f"enc::{uuid4()}@example.com",
            email_hash=f"dhash::{uuid4()}",
            password_hash="pwhash::secret",
            role=role,
        ),
    )


@pytest.fixture
async def org(db_session):
    organization = await organizations_adapter.create(db_session, OrganizationCreate(name="Agencia"))
    admin = await make_user(db_session, organization.id, Role.ADMIN)
    member = await make_user(db_session, organization.id, Role.MEMBER)
    library = await projects_adapter.get_or_create_library(db_session, organization.id, LIBRARY)
    await db_session.commit()
    return organization, admin, member, library


def getter(db_session):
    return lambda project_id, organization_id: projects_adapter.get_project(db_session, project_id, organization_id)


async def test_there_is_one_library_per_organization(db_session, org):
    organization, _, _, library = org

    again = await projects_adapter.get_or_create_library(db_session, organization.id, LIBRARY)

    assert again.id == library.id
    assert library.shared and library.owner_id is None


async def test_every_member_reads_it_and_only_managers_change_it(db_session, org):
    _, admin, member, library = org
    get = getter(db_session)

    assert (await use_cases.resolve_readable_project(library.id, member, get)).id == library.id
    assert (await use_cases.resolve_writable_project(library.id, admin, get)).id == library.id
    with pytest.raises(AuthorizationError):
        await use_cases.resolve_writable_project(library.id, member, get)
    # it is no one's, so no one can rename or delete it as their own
    with pytest.raises(NotFoundError):
        await use_cases.resolve_owned_project(library.id, admin, get)


async def test_another_organization_cannot_see_it(db_session, org):
    _, _, _, library = org
    other = await organizations_adapter.create(db_session, OrganizationCreate(name="Otra"))
    stranger = await make_user(db_session, other.id, Role.OWNER)

    with pytest.raises(NotFoundError):
        await use_cases.resolve_readable_project(library.id, stranger, getter(db_session))


async def test_an_orphaned_project_is_not_shared(db_session, org):
    organization, admin, member, _ = org
    mine = await ProjectFiles(db_session, organization.id, admin.id, FakeBucketStore()).create_project("Privado")
    # what deleting the admin's account leaves: an orphan, for managers to reassign
    await projects_adapter.update_project(db_session, mine.id, {"owner_id": None})

    with pytest.raises(NotFoundError):
        await use_cases.resolve_readable_project(mine.id, member, getter(db_session))


async def test_management_neither_lists_nor_touches_it(db_session, org):
    organization, _, _, library = org

    listed = await projects_adapter.list_projects_for_organization(db_session, organization.id)

    assert library.id not in [p.id for p in listed]
    with pytest.raises(NotFoundError):
        await management_use_cases.resolve_organization_project(library.id, organization.id, getter(db_session))


async def test_its_name_is_reserved(db_session, org):
    organization, _, member, _ = org
    files = ProjectFiles(db_session, organization.id, member.id, FakeBucketStore())

    with pytest.raises(ConflictError):
        await files.create_project("biblioteca")


async def test_an_agent_reads_it_but_never_writes_there(db_session, org):
    organization, admin, member, library = org
    bucket = FakeBucketStore()
    await _admin_upload(db_session, library, admin, bucket)
    files = ProjectFiles(db_session, organization.id, member.id, bucket)

    found, inner = await files.source(await files.workspace(), f"project:{LIBRARY}/Soullens/logo.png")
    assert (found.id, inner) == (library.id, "Soullens/logo.png")
    _, content = await files.read_bytes(found, inner)
    assert content == png()

    for attempt in (
        lambda: files.write(library, "Soullens/logo.png", b"draft", overwrite=True),
        lambda: files.make_folder(library, "Nueva"),
        lambda: files.delete(library, "Soullens/logo.png"),
        lambda: files.move(library, "Soullens/logo.png", "otro.png"),
    ):
        with pytest.raises(AuthorizationError):
            await attempt()
    # even working for an admin
    with pytest.raises(AuthorizationError):
        await ProjectFiles(db_session, organization.id, admin.id, bucket).write(library, "x.png", png())


async def test_the_agent_is_told_what_each_brand_has(db_session, org):
    organization, admin, _, library = org
    await _admin_upload(db_session, library, admin, FakeBucketStore())

    listing = await build_context(db_session, organization.id)

    assert f"project:{LIBRARY}/Soullens/logo.png" in listing
    assert "- Soullens/: logo.png" in listing


async def _admin_upload(db_session, library, admin, bucket):
    """An upload through the panel: the routes' use cases, not the agent's files."""
    from src.projects import paths

    folder_id = await paths.ensure_folder(
        library, ["Soullens"],
        lambda project_id, parent_id, name: projects_adapter.find_entry(db_session, project_id, parent_id, name),
        lambda folder: projects_adapter.create_folder(db_session, folder),
    )
    await paths.store_file(
        project=library, folder_id=folder_id, name="logo.png", content=png(), content_type="image/png",
        uploaded_by=admin.id, overwrite=False,
        find_entry_fn=lambda project_id, parent_id, name: projects_adapter.find_entry(db_session, project_id, parent_id, name),
        create_file_fn=lambda f: projects_adapter.create_file(db_session, f),
        update_file_fn=lambda file_id, changes: projects_adapter.update_file(db_session, file_id, changes),
        bucket_store=bucket,
    )
    await db_session.commit()
