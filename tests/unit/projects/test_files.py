"""The project file system (ProjectFiles) over a fake store: paths, the read-only library,
copy, move, delete and the attachment helpers -- no database."""

from uuid import uuid4

import pytest
from helpers import make_user

from src.core.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from src.projects import config, keys
from src.projects.domain import FileStatus, ProjectCreate
from src.projects.files import ProjectFiles


@pytest.fixture
def files(store, bucket, owner):
    return ProjectFiles(store, owner.organization_id, owner.id, bucket)


async def tree_paths(files, project):
    return [path for path, _entry in await files.tree(project)]


# --- projects ------------------------------------------------------------------


async def test_a_project_is_found_by_name_ignoring_case(files):
    made = await files.create_project("Website")

    assert (await files.project("wEbSiTe")).id == made.id


async def test_an_unknown_project_names_the_ones_that_exist(files):
    await files.create_project("Website")

    with pytest.raises(NotFoundError) as exc:
        await files.project("Nope")

    assert exc.value.code == "project_not_found"
    assert "Website" in exc.value.message


async def test_the_workspace_is_made_the_first_time_it_is_asked_for(files, store):
    workspace = await files.workspace()

    assert workspace.name == config.WORKSPACE_PROJECT
    assert (await files.workspace()).id == workspace.id
    assert len(store.projects) == 1


async def test_the_users_projects_come_first_and_the_library_last(files, store, owner):
    mine = await files.create_project("Website")
    library = await store.get_or_create_library(owner.organization_id, config.LIBRARY_PROJECT)
    # a colleague's project is not listed
    await store.create_project(
        ProjectCreate(organization_id=owner.organization_id, owner_id=uuid4(), name="Theirs")
    )

    listed = await files.projects()

    assert [p.id for p in listed] == [mine.id, library.id]


async def test_a_source_names_another_project_and_never_creates_one(files, store):
    project = await files.create_project("Website")
    other = await files.create_project("Fotos")

    assert await files.source(project, "project:fotos/gato.png") == (other, "gato.png")
    assert await files.source(project, "plain/path.png") == (project, "plain/path.png")
    with pytest.raises(NotFoundError):
        await files.source(project, "project:Missing/x.png")
    assert len(store.projects) == 2


# --- writing and reading -------------------------------------------------------


async def test_writing_makes_the_folders_and_stores_the_bytes(files, store, bucket):
    project = await files.create_project("Website")

    written = await files.write(project, "pages/home/index.txt", b"hello")

    stored, content = await files.read_bytes(project, "pages/home/index.txt")
    assert stored.id == written.id and content == b"hello"
    assert stored.status is FileStatus.READY
    assert keys.file_key(project.organization_id, written.id) in bucket.objects
    assert await tree_paths(files, project) == ["pages", "pages/home", "pages/home/index.txt"]


async def test_writing_over_a_file_is_refused_unless_asked(files):
    project = await files.create_project("Website")
    await files.write(project, "a.txt", b"one")

    with pytest.raises(ConflictError) as exc:
        await files.write(project, "a.txt", b"two")
    await files.write(project, "a.txt", b"two", overwrite=True)

    assert exc.value.code == "project_entry_name_taken"
    assert (await files.read_bytes(project, "a.txt"))[1] == b"two"


async def test_the_library_is_never_written_from_here(files, store, owner):
    library = await store.get_or_create_library(owner.organization_id, config.LIBRARY_PROJECT)

    for attempt in (
        files.write(library, "logo.png", b"x"),
        files.make_folder(library, "brand"),
        files.delete(library, "logo.png"),
    ):
        with pytest.raises(AuthorizationError) as exc:
            await attempt
        assert exc.value.code == "library_read_only"


async def test_a_folder_is_not_a_file(files):
    project = await files.create_project("Website")
    await files.make_folder(project, "pages")

    with pytest.raises(ValidationError) as exc:
        await files.file(project, "pages")

    assert exc.value.code == "project_path_not_a_file"


async def test_a_file_over_the_limit_is_not_read(files):
    project = await files.create_project("Website")
    await files.write(project, "big.bin", b"0123456789")

    with pytest.raises(ValidationError) as exc:
        await files.read_bytes(project, "big.bin", limit=5)

    assert exc.value.code == "project_file_too_large"


async def test_contents_lists_one_level(files):
    project = await files.create_project("Website")
    await files.write(project, "top.txt", b"1")
    await files.write(project, "pages/inner.txt", b"2")

    root = await files.contents(project, "")
    inside = await files.contents(project, "pages")

    assert [f.name for f in root.folders] == ["pages"] and [f.name for f in root.files] == ["top.txt"]
    assert [f.name for f in inside.files] == ["inner.txt"]


# --- copy, move, delete --------------------------------------------------------


async def test_copy_into_an_existing_folder_keeps_the_name(files):
    project = await files.create_project("Website")
    await files.write(project, "src/a.txt", b"payload")
    await files.make_folder(project, "dest")

    count, landed = await files.copy(project, "src/a.txt", project, "dest")

    assert (count, landed) == (1, "dest/a.txt")
    assert (await files.read_bytes(project, "dest/a.txt"))[1] == b"payload"
    assert (await files.read_bytes(project, "src/a.txt"))[1] == b"payload"


async def test_copy_to_a_new_path_renames(files):
    project = await files.create_project("Website")
    await files.write(project, "a.txt", b"payload")

    count, landed = await files.copy(project, "a.txt", project, "backup/b.txt")

    assert (count, landed) == (1, "backup/b.txt")


async def test_move_renames_and_relocates(files):
    project = await files.create_project("Website")
    await files.write(project, "a.txt", b"payload")

    landed = await files.move(project, "a.txt", "sub/b.txt")

    assert landed == "sub/b.txt"
    paths = await tree_paths(files, project)
    assert "sub/b.txt" in paths and "a.txt" not in paths
    assert (await files.read_bytes(project, "sub/b.txt"))[1] == b"payload"


async def test_deleting_a_file_removes_its_object(files, store, bucket):
    project = await files.create_project("Website")
    written = await files.write(project, "a.txt", b"x")

    assert await files.delete(project, "a.txt") == "a.txt"

    assert store.files == {}
    assert bucket.deleted == [keys.file_key(project.organization_id, written.id)]


async def test_deleting_a_folder_removes_everything_inside(files, store, bucket):
    project = await files.create_project("Website")
    top = await files.write(project, "d/x.txt", b"1")
    nested = await files.write(project, "d/e/y.txt", b"2")
    spared = await files.write(project, "keep.txt", b"3")

    assert await files.delete(project, "d") == "d/"

    assert list(store.files) == [spared.id]
    assert set(bucket.deleted) == {
        keys.file_key(project.organization_id, top.id),
        keys.file_key(project.organization_id, nested.id),
    }


# --- attachments ---------------------------------------------------------------


async def test_an_upload_ticket_never_replaces_a_name_already_taken(files):
    project = await files.create_project("Borradores")

    first, _ = await files.upload_ticket(project, "adjuntos", "gato.png", "image/png", 10)
    second, _ = await files.upload_ticket(project, "adjuntos", "gato.png", "image/png", 10)

    assert (first.name, second.name) == ("gato.png", "gato (2).png")
    assert first.status is FileStatus.PENDING


async def test_a_users_own_finished_file_is_found_with_its_path(files):
    project = await files.create_project("Borradores")
    written = await files.write(project, "adjuntos/gato.png", b"img")

    found = await files.owned_file(written.id)

    assert found is not None
    project_file, owning, path = found
    assert (project_file.id, owning.id, path) == (written.id, project.id, "adjuntos/gato.png")


async def test_a_file_still_uploading_is_not_owned_yet(files):
    project = await files.create_project("Borradores")
    pending, _ = await files.upload_ticket(project, "adjuntos", "gato.png", "image/png", 10)

    assert await files.owned_file(pending.id) is None


async def test_someone_elses_file_is_not_owned_even_in_the_same_organization(files, store, bucket, owner):
    colleague = make_user(organization_id=owner.organization_id)
    theirs = ProjectFiles(store, colleague.organization_id, colleague.id, bucket)
    project = await theirs.create_project("Privado")
    written = await theirs.write(project, "secreto.png", b"img")

    assert await files.owned_file(written.id) is None
    assert await files.owned_file(uuid4()) is None


async def test_bytes_of_stays_inside_the_organization(files, store, bucket):
    stranger = make_user()
    theirs = ProjectFiles(store, stranger.organization_id, stranger.id, bucket)
    project = await theirs.create_project("Ajeno")
    written = await theirs.write(project, "a.png", b"img", content_type="image/png")

    assert await files.bytes_of(written.id) is None

    mine = await files.create_project("Mio")
    own = await files.write(mine, "b.png", b"pic", content_type="image/png")
    assert await files.bytes_of(own.id) == (b"pic", "image/png")
