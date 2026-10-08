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
from src.core.exceptions import ApplicationError, AuthorizationError, NotFoundError, ValidationError

from . import config, html_images, links, paths, use_cases
from .domain import FileStatus, Folder, Project, ProjectContents, ProjectFile
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
        """The user's own projects, then the organization's library, which they read but
        never change from here (see _writable)."""
        own = await adapter.list_projects_for_owner(self._session, self._user_id)
        library = await adapter.get_library(self._session, self._organization_id)
        return [*own, library] if library is not None else own

    @staticmethod
    def _writable(project: Project) -> None:
        """The library is changed only by owners and admins, in the panel -- never by an
        agent, whoever it works for: a brand's logo replaced by a draft is a quiet disaster."""
        if project.shared:
            raise AuthorizationError(
                message=(
                    f"'{project.name}' is the organization's shared library: read from it "
                    "(project:" + project.name + "/<path>), but save anything you make in one "
                    "of the user's own projects."
                ),
                code="library_read_only",
            )

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

        if wanted in config.AUTO_CREATED_PROJECTS:
            return await self.create_project(config.AUTO_CREATED_PROJECTS[wanted])

        names = ", ".join(project.name for project in held) or "none yet"
        raise NotFoundError(
            message=f"No project named '{name}'. The user's projects: {names}.",
            code="project_not_found",
        )

    async def source(self, project: Project, path: str) -> tuple[Project, str]:
        """Where a file a tool reads from is: `path` in `project`, or, written as
        project:<name>/<path>, in another of the user's projects. For reading only --
        whatever the tool makes is still saved in `project`. That is how a background
        worker, which saves only in its own task folder, works from the user's images."""
        ref = html_images.project_ref(path)
        if ref is None:
            return project, path
        name, inner = ref
        # looked up, never auto-created: naming a project to read from must not make one
        for held in await self.projects():
            if held.name.lower() == name.lower():
                return held, inner
        names = ", ".join(p.name for p in await self.projects()) or "none yet"
        raise NotFoundError(
            message=f"No project named '{name}' to read {inner} from. The user's projects: {names}.",
            code="project_not_found",
        )

    @staticmethod
    def source_name(path: str) -> str:
        """The path inside its project, for naming what is made from it: an edit of
        project:Borradores/fotos/gato.png is fotos/gato-editado.png, not a folder 'project:Borradores'."""
        ref = html_images.project_ref(path)
        return ref[1] if ref else path

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

    async def read_bytes(
        self, project: Project, path: str, limit: int = config.MAX_TOOL_FILE_BYTES
    ) -> tuple[ProjectFile, bytes]:
        project_file = await self.file(project, path)
        if project_file.size_bytes > limit:
            raise ValidationError(
                message=(
                    f"'{path}' is {project_file.size_bytes:,} bytes, over the "
                    f"{limit:,} byte limit for reading it here"
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
        self._writable(project)
        segments = paths.split(path)
        if not segments:
            raise ValidationError(message="Give a file path, not the root", code="project_path_invalid")

        content_type = content_type or content_type_for(segments[-1])
        if content_type == "text/html":
            content = await self._linked(project, path, content)

        folder_id = await paths.ensure_folder(
            project, segments[:-1], self._find_entry, self._create_folder
        )
        return await paths.store_file(
            project=project,
            folder_id=folder_id,
            name=segments[-1],
            content=content,
            content_type=content_type,
            uploaded_by=self._user_id,
            overwrite=overwrite,
            find_entry_fn=self._find_entry,
            create_file_fn=self._create_file,
            update_file_fn=self._update_file,
            bucket_store=self._bucket,
        )

    # --- a page's images (html_images.py) ---------------------------------------------

    async def _addressed(
        self, project: Project, page_path: str, address: str
    ) -> tuple[Folder | ProjectFile | None, Project] | None:
        """What an address on a page in `project` points at, and the project it is in: a
        path from the page, or project:<name>/<path> for another of the user's projects.
        The entry is None when nothing is there; None altogether when the address is not a
        project path (a URL, data:, an anchor)."""
        if (ref := html_images.project_ref(address)) is not None:
            name, target = ref
            # looked up, never auto-created: a page naming a project must not make one
            held = [p for p in await self.projects() if p.name.lower() == name.lower()]
            if not held:
                return None, project
            owner = held[0]
        elif (target := html_images.project_path(page_path, address)) is not None:
            owner = project
        else:
            return None
        # a path that cannot be a project path at all counts as nothing there
        try:
            return await self.entry(owner, target), owner
        except ApplicationError:
            return None, owner

    async def _linked(self, project: Project, page_path: str, content: bytes) -> bytes:
        """A page about to be saved, with each image it points at by path given the
        image's signed link -- so it shows wherever the page is opened."""
        try:
            html = content.decode("utf-8")
        except UnicodeDecodeError:
            return content

        async def link(address: str) -> str | None:
            addressed = await self._addressed(project, page_path, address)
            found = addressed[0] if addressed else None
            if not isinstance(found, ProjectFile) or not found.content_type.startswith("image/"):
                return None
            return links.view_url(found.id)

        swaps = await html_images.swaps_for(html_images.references(html), link)
        return html_images.replace(html, swaps).encode("utf-8") if swaps else content

    async def embed_images(self, project: Project, page_path: str, html: str) -> tuple[str, list[str]]:
        """The page with every image it uses -- by path or by signed link -- put inside it
        as a data: URI, the only kind of address the PDF renderer loads. Also says which
        it could not: a path to nothing, a file that is not an image, one too big."""
        missing: list[str] = []
        budget = [config.MAX_EMBEDDED_IMAGES_BYTES]

        async def embed(address: str) -> str | None:
            found: tuple[ProjectFile, Project] | None = None
            if (file_id := links.parse(address)) is not None:
                held = await adapter.get_file_with_project(self._session, file_id)
                # a link from this organization only: a page cannot pull in another's files
                if held is not None and held[1].organization_id == self._organization_id:
                    found = held
            elif (addressed := await self._addressed(project, page_path, address)) is not None:
                entry, owner = addressed
                if isinstance(entry, ProjectFile):
                    found = (entry, owner)
            else:
                return None  # a URL elsewhere, data:, an anchor: not ours to resolve

            if found is None or not found[0].content_type.startswith("image/"):
                missing.append(address)
                return None
            image, owner = found
            if image.size_bytes > budget[0]:
                missing.append(f"{address} (too large to embed)")
                return None
            try:
                content = await paths.load_file(owner, image, self._bucket)
            except ApplicationError:
                missing.append(f"{address} (its content could not be read)")
                return None
            budget[0] -= len(content)
            return html_images.data_uri(content, image.content_type)

        swaps = await html_images.swaps_for(html_images.references(html), embed)
        return html_images.replace(html, swaps), missing

    # --- files the client uploads itself (a chat attachment) ----------------------------

    async def upload_ticket(
        self, project: Project, folder_path: str, name: str, content_type: str, size_bytes: int
    ) -> tuple[ProjectFile, str]:
        """A pending file in `folder_path` (made if missing) and the URL its bytes go to.
        Never replaces anything: a name already taken becomes 'name (2).ext'."""
        self._writable(project)
        folder_id = await paths.ensure_folder(
            project, paths.split(folder_path), self._find_entry, self._create_folder
        )
        wanted = use_cases.validate_name(name)
        free = wanted
        stem, dot, suffix = wanted.rpartition(".")
        if not dot:
            stem, suffix = wanted, ""
        for number in range(2, 1000):
            if await self._find_entry(project.id, folder_id, free) is None:
                break
            free = f"{stem} ({number}){dot}{suffix}"

        return await use_cases.request_upload(
            project=project,
            name=free,
            folder_id=folder_id,
            content_type=content_type,
            size_bytes=size_bytes,
            uploaded_by=self._user_id,
            get_folder_fn=self._get_folder,
            find_entry_fn=self._find_entry,
            delete_file_fn=lambda file_id: adapter.delete_file(self._session, file_id),
            create_file_fn=self._create_file,
            bucket_store=self._bucket,
        )

    async def owned_file(self, file_id: UUID) -> tuple[ProjectFile, Project, str] | None:
        """A finished file in one of this user's projects, with its path there; None for
        anything else -- someone else's, still uploading, or gone."""
        found = await adapter.get_file_with_project(self._session, file_id)
        if found is None:
            return None
        project_file, project = found
        if project.owner_id != self._user_id or project.organization_id != self._organization_id:
            return None
        if project_file.status is not FileStatus.READY:
            return None
        for path, entry in await self.tree(project):
            if entry.id == project_file.id:
                return project_file, project, path
        return None

    async def bytes_of(self, file_id: UUID) -> tuple[bytes, str] | None:
        """An organization file's content and type, by its id."""
        found = await adapter.get_file_with_project(self._session, file_id)
        if found is None or found[1].organization_id != self._organization_id:
            return None
        project_file, project = found
        try:
            return await paths.load_file(project, project_file, self._bucket), project_file.content_type
        except ApplicationError:
            return None

    async def make_folder(self, project: Project, path: str) -> None:
        self._writable(project)
        await paths.ensure_folder(project, paths.split(path), self._find_entry, self._create_folder)

    async def copy(
        self, source: Project, source_path: str, target: Project, target_path: str, replace: bool = False
    ) -> tuple[int, str]:
        """Copy with cp's conventions: into an existing folder under the source's own
        name, otherwise to the new path. Returns the file count and where it landed.
        `replace` overwrites files already there (delivery); otherwise they are refused."""
        self._writable(target)
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
            replace,
        )
        return count, landed

    async def move(self, project: Project, source_path: str, target_path: str) -> str:
        self._writable(project)
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
        self._writable(project)
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
