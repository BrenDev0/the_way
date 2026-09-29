from uuid import uuid4

import pytest

from src.core.exceptions import ConflictError, ValidationError
from src.organizations.domain import OrganizationCreate
from src.organizations.sqlalchemy import adapter as organizations_adapter
from src.projects.domain import (
    FileStatus,
    FolderCreate,
    ProjectCreate,
    ProjectFileCreate,
)
from src.projects.sqlalchemy import adapter as projects_adapter
from src.users.domain import Role, UserCreate
from src.users.sqlalchemy import adapter as users_adapter


async def make_user(db_session, organization_id, role=Role.MEMBER):
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
async def owner(db_session):
    organization = await organizations_adapter.create(
        db_session, OrganizationCreate(name="Acme Inc")
    )
    user = await make_user(db_session, organization.id, Role.OWNER)
    await db_session.commit()
    return user


@pytest.fixture
async def project(db_session, owner):
    created = await projects_adapter.create_project(
        db_session,
        ProjectCreate(organization_id=owner.organization_id, owner_id=owner.id, name="Website"),
    )
    await db_session.commit()
    return created


async def folder(db_session, project, name, parent=None):
    return await projects_adapter.create_folder(
        db_session,
        FolderCreate(project_id=project.id, parent_id=parent.id if parent else None, name=name),
    )


async def upload(db_session, project, name, parent=None, size_bytes=10):
    return await projects_adapter.create_file(
        db_session,
        ProjectFileCreate(
            project_id=project.id,
            folder_id=parent.id if parent else None,
            name=name,
            content_type="text/plain",
            size_bytes=size_bytes,
        ),
    )


async def test_a_project_round_trips(db_session, owner, project):
    found = await projects_adapter.get_project(db_session, project.id, owner.organization_id)

    assert found is not None
    assert found.name == "Website"
    assert found.owner_id == owner.id


async def test_another_organization_cannot_fetch_the_project(db_session, project):
    assert await projects_adapter.get_project(db_session, project.id, uuid4()) is None


async def test_project_names_collide_ignoring_case(db_session, owner, project):
    with pytest.raises(ConflictError) as exc:
        await projects_adapter.create_project(
            db_session,
            ProjectCreate(
                organization_id=owner.organization_id, owner_id=owner.id, name="WEBSITE"
            ),
        )

    assert exc.value.code == "project_name_taken"


async def test_root_folder_names_collide_despite_the_null_parent(db_session, project):
    await folder(db_session, project, "assets")
    await db_session.commit()

    with pytest.raises(ConflictError) as exc:
        await folder(db_session, project, "Assets")

    assert exc.value.code == "project_entry_name_taken"


async def test_root_file_names_collide_despite_the_null_folder(db_session, project):
    await upload(db_session, project, "notes.txt")
    await db_session.commit()

    with pytest.raises(ConflictError):
        await upload(db_session, project, "NOTES.txt")


async def test_find_entry_matches_folders_and_files_ignoring_case(db_session, project):
    assets = await folder(db_session, project, "assets")
    readme = await upload(db_session, project, "README.md", parent=assets)
    await db_session.commit()

    found_folder = await projects_adapter.find_entry(db_session, project.id, None, "ASSETS")
    found_file = await projects_adapter.find_entry(db_session, project.id, assets.id, "readme.md")
    elsewhere = await projects_adapter.find_entry(db_session, project.id, None, "readme.md")

    assert found_folder is not None and found_folder.id == assets.id
    assert found_file is not None and found_file.id == readme.id
    assert elsewhere is None


async def test_contents_lists_one_level_sorted_by_name(db_session, project):
    assets = await folder(db_session, project, "assets")
    await folder(db_session, project, "Docs")
    await upload(db_session, project, "b.txt")
    await upload(db_session, project, "A.txt")
    await upload(db_session, project, "nested.txt", parent=assets)
    await db_session.commit()

    root = await projects_adapter.list_contents(db_session, project.id, None)
    inside = await projects_adapter.list_contents(db_session, project.id, assets.id)

    assert [f.name for f in root.folders] == ["assets", "Docs"]
    assert [f.name for f in root.files] == ["A.txt", "b.txt"]
    assert [f.name for f in inside.files] == ["nested.txt"]


async def test_the_tree_holds_everything(db_session, project):
    assets = await folder(db_session, project, "assets")
    icons = await folder(db_session, project, "icons", parent=assets)
    await upload(db_session, project, "logo.svg", parent=icons)
    await db_session.commit()

    tree = await projects_adapter.list_tree(db_session, project.id)

    assert {f.name for f in tree.folders} == {"assets", "icons"}
    assert [f.name for f in tree.files] == ["logo.svg"]


async def test_ancestors_walk_up_to_the_root(db_session, project):
    top = await folder(db_session, project, "top")
    middle = await folder(db_session, project, "middle", parent=top)
    bottom = await folder(db_session, project, "bottom", parent=middle)
    await db_session.commit()

    ancestors = await projects_adapter.list_folder_ancestor_ids(db_session, bottom.id)

    assert set(ancestors) == {bottom.id, middle.id, top.id}


async def test_subtree_files_include_every_level_below(db_session, project):
    top = await folder(db_session, project, "top")
    inner = await folder(db_session, project, "inner", parent=top)
    shallow = await upload(db_session, project, "shallow.txt", parent=top)
    deep = await upload(db_session, project, "deep.txt", parent=inner)
    await upload(db_session, project, "outside.txt")
    await db_session.commit()

    file_ids = await projects_adapter.list_subtree_file_ids(db_session, top.id)

    assert set(file_ids) == {shallow.id, deep.id}


async def test_deleting_a_folder_cascades_through_its_subtree(db_session, project):
    top = await folder(db_session, project, "top")
    inner = await folder(db_session, project, "inner", parent=top)
    await upload(db_session, project, "deep.txt", parent=inner)
    kept = await upload(db_session, project, "kept.txt")
    await db_session.commit()

    assert await projects_adapter.delete_folder(db_session, top.id) is True
    await db_session.commit()

    tree = await projects_adapter.list_tree(db_session, project.id)
    assert tree.folders == []
    assert [f.id for f in tree.files] == [kept.id]


async def test_deleting_a_project_cascades_to_folders_and_files(db_session, owner, project):
    assets = await folder(db_session, project, "assets")
    await upload(db_session, project, "logo.png", parent=assets)
    await db_session.commit()

    assert await projects_adapter.delete_project(db_session, project.id) is True
    await db_session.commit()

    assert await projects_adapter.list_project_file_ids(db_session, project.id) == []
    assert await projects_adapter.get_folder(db_session, assets.id, project.id) is None


async def test_moving_a_folder_updates_its_parent(db_session, project):
    source = await folder(db_session, project, "drafts")
    target = await folder(db_session, project, "archive")
    await db_session.commit()

    moved = await projects_adapter.update_folder(db_session, source.id, {"parent_id": target.id})
    await db_session.commit()

    assert moved is not None
    assert moved.parent_id == target.id


async def test_completing_a_file_stores_a_size_above_two_gigabytes(db_session, project):
    pending = await upload(db_session, project, "video.mov")
    await db_session.commit()

    ready = await projects_adapter.update_file(
        db_session,
        pending.id,
        {"status": FileStatus.READY, "size_bytes": 4 * 1024 * 1024 * 1024},
    )
    await db_session.commit()

    assert ready is not None
    assert ready.status is FileStatus.READY
    assert ready.size_bytes == 4 * 1024 * 1024 * 1024


async def test_fields_outside_the_allow_list_cannot_be_updated(db_session, project):
    pending = await upload(db_session, project, "notes.txt")
    await db_session.commit()

    with pytest.raises(ValidationError) as exc:
        await projects_adapter.update_file(db_session, pending.id, {"project_id": uuid4()})

    assert exc.value.code == "file_field_not_updatable"


async def test_deleting_the_owner_orphans_the_project_for_managers(db_session, owner):
    member = await make_user(db_session, owner.organization_id)
    await db_session.commit()
    orphan = await projects_adapter.create_project(
        db_session,
        ProjectCreate(organization_id=owner.organization_id, owner_id=member.id, name="Left"),
    )
    await db_session.commit()

    await users_adapter.delete_user(db_session, member.id)
    await db_session.commit()

    listed = await projects_adapter.list_projects_for_organization(
        db_session, owner.organization_id
    )
    assert [(p.id, p.owner_id) for p in listed] == [(orphan.id, None)]


async def test_organization_listing_filters_by_owner(db_session, owner, project):
    member = await make_user(db_session, owner.organization_id)
    await projects_adapter.create_project(
        db_session,
        ProjectCreate(organization_id=owner.organization_id, owner_id=member.id, name="Theirs"),
    )
    await db_session.commit()

    everything = await projects_adapter.list_projects_for_organization(
        db_session, owner.organization_id
    )
    mine = await projects_adapter.list_projects_for_owner(db_session, owner.id)

    assert {p.name for p in everything} == {"Website", "Theirs"}
    assert [p.id for p in mine] == [project.id]
