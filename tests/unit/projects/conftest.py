"""What the projects use-case tests share: a fake of every projects port, backed by dicts so
the use cases run against a real tree, and the fixtures that build a project, a folder or an
uploaded file through it."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from helpers import FakeBucketStore, make_user

from src.projects import keys
from src.projects.domain import (
    FileStatus,
    Folder,
    Project,
    ProjectContents,
    ProjectFile,
)
from src.projects.use_cases import files as file_use_cases
from src.projects.use_cases import folders as folder_use_cases
from src.projects.use_cases import projects as projects_use_cases


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

    async def get_library(self, organization_id):
        for project in self.projects.values():
            if project.organization_id == organization_id and project.shared:
                return project
        return None

    async def get_or_create_library(self, organization_id, name):
        found = await self.get_library(organization_id)
        if found is not None:
            return found
        library = Project(
            id=uuid4(),
            organization_id=organization_id,
            owner_id=None,
            name=name,
            created_at=self._now(),
            updated_at=self._now(),
            shared=True,
        )
        self.projects[library.id] = library
        return library

    async def get_file_with_project(self, file_id):
        project_file = self.files.get(file_id)
        if project_file is None:
            return None
        return project_file, self.projects[project_file.project_id]


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
        return await folder_use_cases.create_folder(
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
        project_file, _url = await file_use_cases.request_upload(
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
        return await file_use_cases.complete_upload(
            project=project,
            file_id=project_file.id,
            get_file_fn=store.get_file,
            update_file_fn=store.update_file,
            bucket_store=bucket,
        )

    return run
