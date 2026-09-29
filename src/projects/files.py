"""One user's projects, addressed by name and path, for code running on their behalf.

The agent's tools are thin wrappers over this, and other slices use it directly -- the
CX dataset fetcher and the background worker both keep their files in the user's
workspace project. Every operation is scoped to the user it was built for: a project is
looked up among *their* projects only, the same rule resolve_owned_project applies to the
routes.
"""

import json
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.bucket.ports import BucketStore
from src.core.exceptions import NotFoundError, ValidationError

from . import config, paths, use_cases
from .domain import Folder, Project, ProjectContents, ProjectFile
from .sqlalchemy import adapter

TEXT_TYPES = {
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "text/javascript",
    ".json": "application/json",
    ".ndjson": "application/x-ndjson",
    ".csv": "text/csv",
    ".svg": "image/svg+xml",
    ".xml": "application/xml",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
}


def content_type_for(name: str) -> str:
    suffix = name[name.rfind(".") :].lower() if "." in name else ""
    return TEXT_TYPES.get(suffix, "text/plain")


class ProjectFiles:
    def __init__(
        self,
        session: AsyncSession,
        organization_id: UUID,
        user_id: UUID,
        bucket_store: BucketStore,
    ) -> None:
        self._session = session
        self._organization_id = organization_id
        self._user_id = user_id
        self._bucket = bucket_store

    # --- ports, bound to this session, in the shape the use cases take ---------------

    async def _find_entry(self, project_id: UUID, folder_id: UUID | None, name: str):
        return await adapter.find_entry(self._session, project_id, folder_id, name)

    async def _create_folder(self, folder):
        return await adapter.create_folder(self._session, folder)

    async def _get_folder(self, folder_id: UUID, project_id: UUID):
        return await adapter.get_folder(self._session, folder_id, project_id)

    async def _update_folder(self, folder_id: UUID, changes):
        return await adapter.update_folder(self._session, folder_id, changes)

    async def _create_file(self, project_file):
        return await adapter.create_file(self._session, project_file)

    async def _get_file(self, file_id: UUID, project_id: UUID):
        return await adapter.get_file(self._session, file_id, project_id)

    async def _update_file(self, file_id: UUID, changes):
        return await adapter.update_file(self._session, file_id, changes)

    async def _list_contents(self, project_id: UUID, folder_id: UUID | None):
        return await adapter.list_contents(self._session, project_id, folder_id)

    async def _list_tree(self, project_id: UUID):
        return await adapter.list_tree(self._session, project_id)

    # --- projects ---------------------------------------------------------------------

    async def projects(self) -> Sequence[Project]:
        return await adapter.list_projects_for_owner(self._session, self._user_id)

    async def create_project(self, name: str) -> Project:
        return await use_cases.create_project(
            owner=_Owner(self._user_id, self._organization_id),  # type: ignore[arg-type]
            name=name,
            list_projects_for_owner_fn=lambda owner_id: adapter.list_projects_for_owner(
                self._session, owner_id
            ),
            create_project_fn=lambda project: adapter.create_project(self._session, project),
        )

    async def project(self, name: str) -> Project:
        wanted = name.strip().lower()
        held = await self.projects()
        for project in held:
            if project.name.lower() == wanted:
                return project

        if wanted == config.WORKSPACE_PROJECT:
            return await self.create_project(config.WORKSPACE_PROJECT)

        names = ", ".join(project.name for project in held) or "none yet"
        raise NotFoundError(
            message=f"No project named '{name}'. The user's projects: {names}.",
            code="project_not_found",
        )

    async def workspace(self) -> Project:
        return await self.project(config.WORKSPACE_PROJECT)

    # --- reading ----------------------------------------------------------------------

    async def entry(self, project: Project, path: str) -> Folder | ProjectFile | None:
        return await paths.resolve(project, paths.split(path), self._find_entry)

    async def file(self, project: Project, path: str) -> ProjectFile:
        found = await self.entry(project, path)
        if not isinstance(found, ProjectFile):
            raise ValidationError(
                message=f"'{path}' is a folder, not a file. List it with ListProjectFolder.",
                code="project_path_not_a_file",
            )
        return found

    async def contents(self, project: Project, path: str) -> ProjectContents:
        folder_id = await paths.resolve_folder(project, paths.split(path), self._find_entry)
        return await self._list_contents(project.id, folder_id)

    async def tree(self, project: Project) -> list[tuple[str, Folder | ProjectFile]]:
        return await paths.list_paths(project, self._list_tree)

    async def read_bytes(self, project: Project, path: str) -> tuple[ProjectFile, bytes]:
        project_file = await self.file(project, path)
        if project_file.size_bytes > config.MAX_TOOL_FILE_BYTES:
            raise ValidationError(
                message=(
                    f"'{path}' is {project_file.size_bytes:,} bytes, over the "
                    f"{config.MAX_TOOL_FILE_BYTES:,} byte limit for reading it here"
                ),
                code="project_file_too_large",
            )
        return project_file, await paths.load_file(project, project_file, self._bucket)

    async def read_json_lines(self, project: Project, path: str) -> list[dict]:
        project_file = await self.file(project, path)
        data = await paths.load_file(project, project_file, self._bucket)
        return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]

    # --- writing ----------------------------------------------------------------------

    async def write(
        self,
        project: Project,
        path: str,
        content: bytes,
        overwrite: bool = False,
        content_type: str | None = None,
    ) -> ProjectFile:
        segments = paths.split(path)
        if not segments:
            raise ValidationError(message="Give a file path, not the root", code="project_path_invalid")

        folder_id = await paths.ensure_folder(
            project, segments[:-1], self._find_entry, self._create_folder
        )
        return await paths.store_file(
            project=project,
            folder_id=folder_id,
            name=segments[-1],
            content=content,
            content_type=content_type or content_type_for(segments[-1]),
            uploaded_by=self._user_id,
            overwrite=overwrite,
            find_entry_fn=self._find_entry,
            create_file_fn=self._create_file,
            update_file_fn=self._update_file,
            bucket_store=self._bucket,
        )

    async def make_folder(self, project: Project, path: str) -> None:
        await paths.ensure_folder(project, paths.split(path), self._find_entry, self._create_folder)

    async def copy(
        self, source: Project, source_path: str, target: Project, target_path: str
    ) -> tuple[int, str]:
        """Copy with cp's conventions: into an existing folder under the source's own
        name, otherwise to the new path. Returns the file count and where it landed."""
        entry = await self.entry(source, source_path)
        if entry is None:
            raise ValidationError(message="Cannot copy a whole project root", code="project_path_invalid")

        folder_id, name, landed = await self._destination(target, target_path, entry.name)
        count = await paths.copy_entry(
            source,
            entry,
            target,
            folder_id,
            name,
            self._user_id,
            self._find_entry,
            self._create_folder,
            self._create_file,
            self._update_file,
            self._list_contents,
            self._bucket,
        )
        return count, landed

    async def move(self, project: Project, source_path: str, target_path: str) -> str:
        entry = await self.entry(project, source_path)
        if entry is None:
            raise ValidationError(message="Cannot move a project root", code="project_path_invalid")

        folder_id, name, landed = await self._destination(project, target_path, entry.name)

        if isinstance(entry, Folder):
            if entry.name != name:
                entry = await use_cases.rename_folder(
                    project, entry.id, name, self._get_folder, self._find_entry, self._update_folder
                )
            if entry.parent_id != folder_id:
                await use_cases.move_folder(
                    project,
                    entry.id,
                    folder_id,
                    self._get_folder,
                    lambda folder: adapter.list_folder_ancestor_ids(self._session, folder),
                    self._find_entry,
                    self._update_folder,
                )
            return landed

        if entry.name != name:
            entry = await use_cases.rename_file(
                project, entry.id, name, self._get_file, self._find_entry, self._update_file
            )
        if entry.folder_id != folder_id:
            await use_cases.move_file(
                project,
                entry.id,
                folder_id,
                self._get_file,
                self._get_folder,
                self._find_entry,
                self._update_file,
            )
        return landed

    async def delete(self, project: Project, path: str) -> str:
        entry = await self.entry(project, path)
        if entry is None:
            raise ValidationError(
                message="Cannot delete a project root from here; delete the project instead",
                code="project_path_invalid",
            )

        if isinstance(entry, Folder):
            await use_cases.delete_folder(
                project,
                entry.id,
                self._get_folder,
                lambda folder: adapter.list_subtree_file_ids(self._session, folder),
                lambda folder: adapter.delete_folder(self._session, folder),
                self._bucket,
            )
            return f"{paths.join(paths.split(path))}/"

        await use_cases.delete_file(
            project,
            entry.id,
            self._get_file,
            lambda file_id: adapter.delete_file(self._session, file_id),
            self._bucket,
        )
        return paths.join(paths.split(path))

    async def _destination(
        self, project: Project, target_path: str, source_name: str
    ) -> tuple[UUID | None, str, str]:
        segments = paths.split(target_path)

        try:
            existing = await paths.resolve(project, segments, self._find_entry)
        except NotFoundError:
            existing = None

        if segments == [] or isinstance(existing, Folder):
            folder_id = existing.id if isinstance(existing, Folder) else None
            return folder_id, source_name, paths.join([*segments, source_name])

        folder_id = await paths.ensure_folder(
            project, segments[:-1], self._find_entry, self._create_folder
        )
        return folder_id, segments[-1], paths.join(segments)


class _Owner:
    """The two fields create_project reads off a User, without loading the whole user."""

    def __init__(self, user_id: UUID, organization_id: UUID) -> None:
        self.id = user_id
        self.organization_id = organization_id
