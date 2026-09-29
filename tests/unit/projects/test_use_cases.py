from datetime import UTC, datetime
from uuid import uuid4

import pytest
from helpers import FakeBucketStore, make_user

from src.core.exceptions import ConflictError, NotFoundError, ValidationError
from src.projects import config, keys
from src.projects import use_cases as projects_use_cases
from src.projects.domain import (
    FileStatus,
    Folder,
    Project,
    ProjectContents,
    ProjectFile,
)
from src.projects.management import use_cases as management_use_cases


class FakeProjectStore:
    """Every projects port, backed by dicts, so use cases run against a real tree."""

    def __init__(self) -> None:
        self.projects: dict = {}
        self.folders: dict = {}
        self.files: dict = {}

    @staticmethod
    def _now():
        return datetime.now(UTC)

    async def create_project(self, create):
        project = Project(
            id=uuid4(),
            organization_id=create.organization_id,
            owner_id=create.owner_id,
            name=create.name,
            created_at=self._now(),
            updated_at=self._now(),
        )
        self.projects[project.id] = project
        return project

    async def list_projects_for_owner(self, owner_id):
        return [p for p in self.projects.values() if p.owner_id == owner_id]

    async def list_projects_for_organization(self, organization_id, owner_id=None):
        return [
            p
            for p in self.projects.values()
            if p.organization_id == organization_id
            and (owner_id is None or p.owner_id == owner_id)
        ]

    async def get_project(self, project_id, organization_id):
        project = self.projects.get(project_id)
        return project if project and project.organization_id == organization_id else None

    async def update_project(self, project_id, changes):
        project = self.projects.get(project_id)
        if project is None:
            return None
        for field, value in changes.items():
            setattr(project, field, value)
        return project

    async def delete_project(self, project_id):
        if self.projects.pop(project_id, None) is None:
            return False
        self.folders = {k: f for k, f in self.folders.items() if f.project_id != project_id}
        self.files = {k: f for k, f in self.files.items() if f.project_id != project_id}
        return True

    async def list_project_file_ids(self, project_id):
        return [f.id for f in self.files.values() if f.project_id == project_id]

    async def list_contents(self, project_id, folder_id):
        return ProjectContents(
            folders=[
                f for f in self.folders.values()
                if f.project_id == project_id and f.parent_id == folder_id
            ],
            files=[
                f for f in self.files.values()
                if f.project_id == project_id and f.folder_id == folder_id
            ],
        )

    async def list_tree(self, project_id):
        return ProjectContents(
            folders=[f for f in self.folders.values() if f.project_id == project_id],
            files=[f for f in self.files.values() if f.project_id == project_id],
        )

    async def find_entry(self, project_id, folder_id, name):
        for folder in self.folders.values():
            if (folder.project_id, folder.parent_id) == (project_id, folder_id) and (
                folder.name.lower() == name.lower()
            ):
                return folder
        for project_file in self.files.values():
            if (project_file.project_id, project_file.folder_id) == (project_id, folder_id) and (
                project_file.name.lower() == name.lower()
            ):
                return project_file
        return None

    async def create_folder(self, create):
        folder = Folder(
            id=uuid4(),
            project_id=create.project_id,
            parent_id=create.parent_id,
            name=create.name,
            created_at=self._now(),
            updated_at=self._now(),
        )
        self.folders[folder.id] = folder
        return folder

    async def get_folder(self, folder_id, project_id):
        folder = self.folders.get(folder_id)
        return folder if folder and folder.project_id == project_id else None

    async def update_folder(self, folder_id, changes):
        folder = self.folders.get(folder_id)
        if folder is None:
            return None
        for field, value in changes.items():
            setattr(folder, field, value)
        return folder

    def _subtree(self, folder_id):
        found = {folder_id}
        grew = True
        while grew:
            below = {f.id for f in self.folders.values() if f.parent_id in found}
            grew = not below <= found
            found |= below
        return found

    async def delete_folder(self, folder_id):
        if folder_id not in self.folders:
            return False
        doomed = self._subtree(folder_id)
        self.folders = {k: f for k, f in self.folders.items() if k not in doomed}
        self.files = {k: f for k, f in self.files.items() if f.folder_id not in doomed}
        return True

    async def list_folder_ancestor_ids(self, folder_id):
        chain = []
        current = self.folders.get(folder_id)
        while current is not None:
            chain.append(current.id)
            current = self.folders.get(current.parent_id)
        return chain

    async def list_subtree_file_ids(self, folder_id):
        doomed = self._subtree(folder_id)
        return [f.id for f in self.files.values() if f.folder_id in doomed]

    async def create_file(self, create):
        project_file = ProjectFile(
            id=uuid4(),
            project_id=create.project_id,
            folder_id=create.folder_id,
            name=create.name,
            content_type=create.content_type,
            size_bytes=create.size_bytes,
            status=FileStatus.PENDING,
            uploaded_by=create.uploaded_by,
            created_at=self._now(),
            updated_at=self._now(),
        )
        self.files[project_file.id] = project_file
        return project_file

    async def get_file(self, file_id, project_id):
        project_file = self.files.get(file_id)
        return project_file if project_file and project_file.project_id == project_id else None

    async def update_file(self, file_id, changes):
        project_file = self.files.get(file_id)
        if project_file is None:
            return None
        for field, value in changes.items():
            setattr(project_file, field, value)
        return project_file

    async def delete_file(self, file_id):
        return self.files.pop(file_id, None) is not None


@pytest.fixture
def store():
    return FakeProjectStore()


@pytest.fixture
def bucket():
    return FakeBucketStore()


@pytest.fixture
def owner():
    return make_user()


@pytest.fixture
def new_project(store, owner):
    async def run(name="Website", user=None):
        return await projects_use_cases.create_project(
            owner=user or owner,
            name=name,
            list_projects_for_owner_fn=store.list_projects_for_owner,
            create_project_fn=store.create_project,
        )

    return run


@pytest.fixture
def new_folder(store):
    async def run(project, name="assets", parent_id=None):
        return await projects_use_cases.create_folder(
            project=project,
            name=name,
            parent_id=parent_id,
            get_folder_fn=store.get_folder,
            find_entry_fn=store.find_entry,
            create_folder_fn=store.create_folder,
        )

    return run


@pytest.fixture
def upload(store, bucket, owner):
    async def run(project, name="logo.png", folder_id=None, size_bytes=1024, complete=True):
        project_file, _url = await projects_use_cases.request_upload(
            project=project,
            name=name,
            folder_id=folder_id,
            content_type="image/png",
            size_bytes=size_bytes,
            uploaded_by=owner.id,
            get_folder_fn=store.get_folder,
            find_entry_fn=store.find_entry,
            delete_file_fn=store.delete_file,
            create_file_fn=store.create_file,
            bucket_store=bucket,
        )
        if not complete:
            return project_file

        bucket.objects[keys.file_key(project.organization_id, project_file.id)] = size_bytes
        return await projects_use_cases.complete_upload(
            project=project,
            file_id=project_file.id,
            get_file_fn=store.get_file,
            update_file_fn=store.update_file,
            bucket_store=bucket,
        )

    return run


# --- names -------------------------------------------------------------------


@pytest.mark.parametrize("name", ["a", "Report 2026.pdf", "  padded  ", ".gitignore", "ñandú"])
def test_ordinary_names_are_accepted(name):
    assert projects_use_cases.validate_name(name) == name.strip()


@pytest.mark.parametrize(
    "name",
    ["", "   ", ".", "..", "trailing.", "a/b", "a\\b", "what?", "a:b", "tab\there", "x" * 256],
)
def test_names_windows_cannot_store_are_rejected(name):
    with pytest.raises(ValidationError) as exc:
        projects_use_cases.validate_name(name)

    assert exc.value.code == "project_name_invalid"


@pytest.mark.parametrize("name", ["CON", "nul", "com1", "LPT9.txt", "aux.tar.gz"])
def test_windows_reserved_device_names_are_rejected(name):
    with pytest.raises(ValidationError):
        projects_use_cases.validate_name(name)


# --- projects ----------------------------------------------------------------


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


# --- folders -----------------------------------------------------------------


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

    renamed = await projects_use_cases.rename_folder(
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
        return await projects_use_cases.move_folder(
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

    await projects_use_cases.delete_folder(
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


# --- files -------------------------------------------------------------------


async def test_an_upload_starts_pending_with_a_presigned_url(store, bucket, new_project, upload):
    project = await new_project()

    project_file = await upload(project, complete=False)

    assert project_file.status is FileStatus.PENDING
    assert bucket.presigned[0][0] == keys.file_key(project.organization_id, project_file.id)
    assert bucket.presigned[0][2] == config.UPLOAD_URL_TTL_SECONDS


async def test_the_bucket_key_depends_only_on_the_file_id(new_project, new_folder, upload):
    project = await new_project()
    folder = await new_folder(project)

    project_file = await upload(project, "logo.png", folder_id=folder.id, complete=False)

    key = keys.file_key(project.organization_id, project_file.id)
    assert "logo" not in key
    assert str(folder.id) not in key


async def test_completing_records_the_size_the_bucket_actually_holds(
    store, bucket, new_project, upload
):
    project = await new_project()
    pending = await upload(project, size_bytes=10, complete=False)
    bucket.objects[keys.file_key(project.organization_id, pending.id)] = 4096

    ready = await projects_use_cases.complete_upload(
        project=project,
        file_id=pending.id,
        get_file_fn=store.get_file,
        update_file_fn=store.update_file,
        bucket_store=bucket,
    )

    assert ready.status is FileStatus.READY
    assert ready.size_bytes == 4096


async def test_completing_before_the_upload_is_a_conflict(store, bucket, new_project, upload):
    project = await new_project()
    pending = await upload(project, complete=False)

    with pytest.raises(ConflictError) as exc:
        await projects_use_cases.complete_upload(
            project=project,
            file_id=pending.id,
            get_file_fn=store.get_file,
            update_file_fn=store.update_file,
            bucket_store=bucket,
        )

    assert exc.value.code == "file_not_uploaded"


async def test_a_file_larger_than_s3_allows_is_refused(new_project, upload):
    project = await new_project()

    with pytest.raises(ValidationError) as exc:
        await upload(project, size_bytes=config.MAX_FILE_BYTES + 1, complete=False)

    assert exc.value.code == "file_too_large"


async def test_an_empty_file_can_be_uploaded(new_project, upload):
    project = await new_project()

    assert (await upload(project, "empty.txt", size_bytes=0)).size_bytes == 0


async def test_uploading_over_a_finished_file_is_a_conflict(new_project, upload):
    project = await new_project()
    await upload(project, "logo.png")

    with pytest.raises(ConflictError) as exc:
        await upload(project, "LOGO.png")

    assert exc.value.code == "project_entry_name_taken"


async def test_uploading_over_an_abandoned_upload_replaces_it(
    store, bucket, new_project, upload
):
    project = await new_project()
    abandoned = await upload(project, "logo.png", complete=False)

    fresh = await upload(project, "logo.png", complete=False)

    assert list(store.files) == [fresh.id]
    assert keys.file_key(project.organization_id, abandoned.id) in bucket.deleted


async def test_a_download_url_names_the_file(store, bucket, new_project, upload):
    project = await new_project()
    ready = await upload(project, "logo.png")

    _file, url = await projects_use_cases.request_download(
        project=project, file_id=ready.id, get_file_fn=store.get_file, bucket_store=bucket
    )

    assert url == bucket.download_url
    assert bucket.presigned_gets == [
        (
            keys.file_key(project.organization_id, ready.id),
            config.DOWNLOAD_URL_TTL_SECONDS,
            "logo.png",
        )
    ]


async def test_a_pending_file_cannot_be_downloaded(store, bucket, new_project, upload):
    project = await new_project()
    pending = await upload(project, complete=False)

    with pytest.raises(ConflictError):
        await projects_use_cases.request_download(
            project=project, file_id=pending.id, get_file_fn=store.get_file, bucket_store=bucket
        )


async def test_a_file_from_another_project_is_not_found(store, bucket, new_project, upload):
    project = await new_project("One")
    other = await new_project("Two")
    foreign = await upload(other)

    with pytest.raises(NotFoundError) as exc:
        await projects_use_cases.request_download(
            project=project, file_id=foreign.id, get_file_fn=store.get_file, bucket_store=bucket
        )

    assert exc.value.code == "file_not_found"


async def test_renaming_a_file_leaves_the_bucket_alone(store, bucket, new_project, upload):
    project = await new_project()
    ready = await upload(project, "draft.txt")

    renamed = await projects_use_cases.rename_file(
        project=project,
        file_id=ready.id,
        name="final.txt",
        get_file_fn=store.get_file,
        find_entry_fn=store.find_entry,
        update_file_fn=store.update_file,
    )

    assert renamed.name == "final.txt"
    assert bucket.deleted == []


async def test_a_file_moves_into_a_folder_and_back(store, new_project, new_folder, upload):
    project = await new_project()
    folder = await new_folder(project)
    ready = await upload(project)

    async def move(folder_id):
        return await projects_use_cases.move_file(
            project=project,
            file_id=ready.id,
            folder_id=folder_id,
            get_file_fn=store.get_file,
            get_folder_fn=store.get_folder,
            find_entry_fn=store.find_entry,
            update_file_fn=store.update_file,
        )

    assert (await move(folder.id)).folder_id == folder.id
    assert (await move(None)).folder_id is None


async def test_deleting_a_file_removes_its_object(store, bucket, new_project, upload):
    project = await new_project()
    ready = await upload(project)

    await projects_use_cases.delete_file(
        project=project,
        file_id=ready.id,
        get_file_fn=store.get_file,
        delete_file_fn=store.delete_file,
        bucket_store=bucket,
    )

    assert store.files == {}
    assert bucket.deleted == [keys.file_key(project.organization_id, ready.id)]


async def test_contents_of_a_missing_folder_is_not_found(store, new_project):
    project = await new_project()

    with pytest.raises(NotFoundError):
        await projects_use_cases.list_contents(
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

    contents = await projects_use_cases.list_contents(
        project=project,
        folder_id=None,
        get_folder_fn=store.get_folder,
        list_contents_fn=store.list_contents,
    )

    assert [f.name for f in contents.folders] == ["assets"]
    assert [f.name for f in contents.files] == ["top.png"]


# --- management --------------------------------------------------------------


async def test_a_manager_resolves_any_project_in_their_organization(store, new_project, owner):
    project = await new_project()

    resolved = await management_use_cases.resolve_organization_project(
        project.id, owner.organization_id, store.get_project
    )

    assert resolved.id == project.id


async def test_a_manager_cannot_reach_another_organizations_project(store, new_project):
    project = await new_project()

    with pytest.raises(NotFoundError):
        await management_use_cases.resolve_organization_project(
            project.id, uuid4(), store.get_project
        )


async def test_managers_can_filter_projects_by_owner(store, new_project, owner):
    await new_project("Mine")
    colleague = make_user(organization_id=owner.organization_id)
    await new_project("Theirs", user=colleague)

    everything = await management_use_cases.list_organization_projects(
        owner.organization_id, store.list_projects_for_organization
    )
    theirs = await management_use_cases.list_organization_projects(
        owner.organization_id, store.list_projects_for_organization, owner_id=colleague.id
    )

    assert {p.name for p in everything} == {"Mine", "Theirs"}
    assert [p.name for p in theirs] == ["Theirs"]


async def test_a_project_transfers_to_a_colleague(store, new_project, owner):
    project = await new_project()
    colleague = make_user(organization_id=owner.organization_id)

    async def get_user_by_id_fn(user_id):
        return colleague if user_id == colleague.id else None

    transferred = await management_use_cases.transfer_project(
        project=project,
        new_owner_id=colleague.id,
        get_user_by_id_fn=get_user_by_id_fn,
        update_project_fn=store.update_project,
    )

    assert transferred.owner_id == colleague.id


async def test_a_project_cannot_transfer_outside_the_organization(store, new_project):
    project = await new_project()
    outsider = make_user()

    async def get_user_by_id_fn(_user_id):
        return outsider

    with pytest.raises(NotFoundError) as exc:
        await management_use_cases.transfer_project(
            project=project,
            new_owner_id=outsider.id,
            get_user_by_id_fn=get_user_by_id_fn,
            update_project_fn=store.update_project,
        )

    assert exc.value.code == "user_not_found"
