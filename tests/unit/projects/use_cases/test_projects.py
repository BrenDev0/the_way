
import pytest
from helpers import make_user

from src.core.exceptions import ConflictError, NotFoundError
from src.projects import config, keys
from src.projects.use_cases import projects as projects_use_cases


async def test_a_project_belongs_to_its_creator(new_project, owner):
    project = await new_project()

    assert project.owner_id == owner.id
    assert project.organization_id == owner.organization_id


async def test_project_names_are_unique_per_owner_ignoring_case(new_project):
    await new_project("Website")

    with pytest.raises(ConflictError) as exc:
        await new_project("WEBSITE")

    assert exc.value.code == "project_name_taken"


async def test_two_users_may_use_the_same_project_name(new_project, owner):
    await new_project("Website")
    colleague = make_user(organization_id=owner.organization_id)

    assert (await new_project("Website", user=colleague)).owner_id == colleague.id


async def test_the_owner_resolves_their_project(store, new_project, owner):
    project = await new_project()

    resolved = await projects_use_cases.resolve_owned_project(project.id, owner, store.get_project)

    assert resolved.id == project.id


async def test_a_colleague_cannot_see_someone_elses_project(store, new_project, owner):
    project = await new_project()
    colleague = make_user(organization_id=owner.organization_id)

    with pytest.raises(NotFoundError) as exc:
        await projects_use_cases.resolve_owned_project(project.id, colleague, store.get_project)

    assert exc.value.code == "project_not_found"


async def test_an_orphaned_project_is_invisible_to_regular_users(store, new_project, owner):
    project = await new_project()
    project.owner_id = None

    with pytest.raises(NotFoundError):
        await projects_use_cases.resolve_owned_project(project.id, owner, store.get_project)


async def test_deleting_a_project_removes_every_object_in_the_bucket(
    store, bucket, new_project, new_folder, upload
):
    project = await new_project()
    folder = await new_folder(project)
    top = await upload(project, "top.png")
    nested = await upload(project, "nested.png", folder_id=folder.id)

    await projects_use_cases.delete_project(
        project=project,
        list_project_file_ids_fn=store.list_project_file_ids,
        delete_project_fn=store.delete_project,
        bucket_store=bucket,
    )

    assert set(bucket.deleted) == {
        keys.file_key(project.organization_id, top.id),
        keys.file_key(project.organization_id, nested.id),
    }
    assert store.projects == {}


# --- the organization's library ----------------------------------------------


async def test_the_library_is_made_on_the_first_ask_and_reused_after(store, owner):
    first = await projects_use_cases.get_library(owner.organization_id, store.get_or_create_library)
    second = await projects_use_cases.get_library(owner.organization_id, store.get_or_create_library)

    assert first.id == second.id
    assert first.shared is True
    assert first.owner_id is None
    assert first.name == config.LIBRARY_PROJECT
    assert len(store.projects) == 1


async def test_each_organization_has_its_own_library(store, owner):
    other = make_user()

    mine = await projects_use_cases.get_library(owner.organization_id, store.get_or_create_library)
    theirs = await projects_use_cases.get_library(other.organization_id, store.get_or_create_library)

    assert mine.id != theirs.id
