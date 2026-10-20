from uuid import uuid4

import pytest

from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.projects import keys
from src.projects.use_cases import folders as folder_use_cases


async def test_folders_nest(new_project, new_folder):
    project = await new_project()
    parent = await new_folder(project, "assets")

    child = await new_folder(project, "icons", parent_id=parent.id)

    assert child.parent_id == parent.id


async def test_a_folder_in_a_missing_parent_is_refused(new_project, new_folder):
    project = await new_project()

    with pytest.raises(NotFoundError) as exc:
        await new_folder(project, "icons", parent_id=uuid4())

    assert exc.value.code == "folder_not_found"


async def test_a_parent_from_another_project_is_refused(new_project, new_folder):
    project = await new_project("One")
    other = await new_project("Two")
    foreign = await new_folder(other)

    with pytest.raises(NotFoundError):
        await new_folder(project, "icons", parent_id=foreign.id)


async def test_a_folder_cannot_share_a_name_with_a_file_beside_it(new_project, new_folder, upload):
    project = await new_project()
    await upload(project, "notes")

    with pytest.raises(ConflictError) as exc:
        await new_folder(project, "Notes")

    assert exc.value.code == "project_entry_name_taken"


async def test_the_same_folder_name_is_fine_in_different_parents(new_project, new_folder):
    project = await new_project()
    first = await new_folder(project, "a")
    second = await new_folder(project, "b")

    await new_folder(project, "shared", parent_id=first.id)
    await new_folder(project, "shared", parent_id=second.id)


async def test_renaming_a_folder_to_its_own_name_in_new_case_is_allowed(
    store, new_project, new_folder
):
    project = await new_project()
    folder = await new_folder(project, "assets")

    renamed = await folder_use_cases.rename_folder(
        project=project,
        folder_id=folder.id,
        name="Assets",
        get_folder_fn=store.get_folder,
        find_entry_fn=store.find_entry,
        update_folder_fn=store.update_folder,
    )

    assert renamed.name == "Assets"


@pytest.fixture
def move_folder(store):
    async def run(project, folder_id, parent_id):
        return await folder_use_cases.move_folder(
            project=project,
            folder_id=folder_id,
            parent_id=parent_id,
            get_folder_fn=store.get_folder,
            list_folder_ancestor_ids_fn=store.list_folder_ancestor_ids,
            find_entry_fn=store.find_entry,
            update_folder_fn=store.update_folder,
        )

    return run


async def test_a_folder_moves_under_another(new_project, new_folder, move_folder):
    project = await new_project()
    source = await new_folder(project, "drafts")
    target = await new_folder(project, "archive")

    moved = await move_folder(project, source.id, target.id)

    assert moved.parent_id == target.id


async def test_a_folder_moves_back_to_the_root(new_project, new_folder, move_folder):
    project = await new_project()
    parent = await new_folder(project, "archive")
    child = await new_folder(project, "drafts", parent_id=parent.id)

    moved = await move_folder(project, child.id, None)

    assert moved.parent_id is None


async def test_a_folder_cannot_move_into_itself(new_project, new_folder, move_folder):
    project = await new_project()
    folder = await new_folder(project)

    with pytest.raises(ValidationError) as exc:
        await move_folder(project, folder.id, folder.id)

    assert exc.value.code == "folder_move_into_self"


async def test_a_folder_cannot_move_into_its_own_descendant(new_project, new_folder, move_folder):
    project = await new_project()
    top = await new_folder(project, "top")
    middle = await new_folder(project, "middle", parent_id=top.id)
    bottom = await new_folder(project, "bottom", parent_id=middle.id)

    with pytest.raises(ValidationError):
        await move_folder(project, top.id, bottom.id)


async def test_a_move_onto_an_existing_name_is_a_conflict(new_project, new_folder, move_folder):
    project = await new_project()
    target = await new_folder(project, "archive")
    await new_folder(project, "drafts", parent_id=target.id)
    source = await new_folder(project, "Drafts")

    with pytest.raises(ConflictError):
        await move_folder(project, source.id, target.id)


async def test_deleting_a_folder_removes_objects_in_every_subfolder(
    store, bucket, new_project, new_folder, upload
):
    project = await new_project()
    top = await new_folder(project, "top")
    inner = await new_folder(project, "inner", parent_id=top.id)
    deep = await upload(project, "deep.png", folder_id=inner.id)
    spared = await upload(project, "spared.png")

    await folder_use_cases.delete_folder(
        project=project,
        folder_id=top.id,
        get_folder_fn=store.get_folder,
        list_subtree_file_ids_fn=store.list_subtree_file_ids,
        delete_folder_fn=store.delete_folder,
        bucket_store=bucket,
    )

    assert bucket.deleted == [keys.file_key(project.organization_id, deep.id)]
    assert list(store.files) == [spared.id]
    assert store.folders == {}


async def test_contents_of_a_missing_folder_is_not_found(store, new_project):
    project = await new_project()

    with pytest.raises(NotFoundError):
        await folder_use_cases.list_contents(
            project=project,
            folder_id=uuid4(),
            get_folder_fn=store.get_folder,
            list_contents_fn=store.list_contents,
        )


async def test_contents_only_lists_one_level(store, new_project, new_folder, upload):
    project = await new_project()
    folder = await new_folder(project)
    await upload(project, "top.png")
    await upload(project, "nested.png", folder_id=folder.id)

    contents = await folder_use_cases.list_contents(
        project=project,
        folder_id=None,
        get_folder_fn=store.get_folder,
        list_contents_fn=store.list_contents,
    )

    assert [f.name for f in contents.folders] == ["assets"]
    assert [f.name for f in contents.files] == ["top.png"]
