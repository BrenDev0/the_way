import re
import tempfile
from pathlib import Path

from src.core.tools.context import ToolContext
from src.core.tools.domain import Tool, truncate
from src.documents import extraction

from . import config
from .domain import Folder
from .files import ProjectFiles
from .tool_schemas import (
    CopyProjectPath,
    CreateProject,
    CreateProjectFolder,
    DeleteProjectPath,
    EditProjectFile,
    FindProjectFiles,
    ListProjectFolder,
    ListProjects,
    MoveProjectPath,
    ReadProjectFile,
    RenameProjectPath,
    WriteProjectFile,
)

EXTRACTED_SUFFIXES = extraction.PDF_SUFFIXES | extraction.WORD_SUFFIXES


def decode_text(data: bytes, name: str) -> str:
    """The text of a file, or a ValueError saying why there is none.

    Line endings come back as \\n whatever they were stored as: an edit whose old_string
    was written with \\n must match a file that happens to hold \\r\\n. A run of carriage
    returns before a newline is repaired too, which is the damage a Windows round trip
    leaves behind.
    """
    suffix = extraction.suffix_of(name)

    if suffix in EXTRACTED_SUFFIXES:
        with tempfile.TemporaryDirectory() as workspace:
            source = Path(workspace) / f"file{suffix}"
            source.write_bytes(data)
            return extraction.extract(source, name)

    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    elif b"\x00" in data[:4096]:
        raise ValueError(
            f"'{name}' looks like a binary file, not text (it contains null bytes), so it "
            f"was not decoded."
        )
    else:
        text = next(
            (decoded for decoded in _attempts(data) if decoded is not None),
            data.decode("utf-8", errors="replace"),
        )

    return re.sub(r"\r+\n", "\n", text).replace("\r", "\n")


def _attempts(data: bytes):
    for encoding in extraction.TEXT_ENCODINGS:
        try:
            yield data.decode(encoding)
        except UnicodeDecodeError:
            yield None


def _listing(entries) -> str:
    lines = []
    for entry in entries:
        if isinstance(entry, Folder):
            lines.append(f"{entry.name}/")
        else:
            pending = "" if entry.status == "ready" else "  [upload not finished]"
            lines.append(f"{entry.name}  ({entry.size_bytes:,} bytes){pending}")
    return "\n".join(lines) or "(empty folder)"


def build(context: ToolContext) -> dict[str, Tool]:
    files = ProjectFiles(
        context.session, context.organization_id, context.user_id, context.bucket_store
    )

    async def list_projects() -> str:
        projects = await files.projects()
        if not projects:
            return "The user has no projects yet. Create one with CreateProject."
        return "\n".join(project.name for project in projects)

    async def create_project(name: str) -> str:
        project = await files.create_project(name)
        return f"Created project '{project.name}'."

    async def list_project_folder(project: str, path: str = ".") -> str:
        target = await files.project(project)
        contents = await files.contents(target, path)
        return _listing((*contents.folders, *contents.files))

    async def find_project_files(project: str, query: str) -> str:
        target = await files.project(project)
        terms = [term for term in re.split(r"[^a-z0-9]+", query.lower()) if term]
        if not terms:
            return "Give something to search for -- a filename, a word from one, or a folder name."

        hits = []
        for path, entry in await files.tree(target):
            if all(term in path.lower() for term in terms):
                name_hits = sum(1 for term in terms if term in entry.name.lower())
                shown = f"{path}/" if isinstance(entry, Folder) else path
                hits.append((-name_hits, len(path), shown))

        if not hits:
            return (
                f"Nothing in {target.name} matches all of {terms}. Try fewer or different "
                f"words, or list a folder with ListProjectFolder."
            )

        hits.sort()
        lines = [shown for _, _, shown in hits[: config.MAX_SEARCH_RESULTS]]
        if len(hits) > config.MAX_SEARCH_RESULTS:
            lines.append(f"... and {len(hits) - config.MAX_SEARCH_RESULTS} more; narrow the query")
        return "\n".join(lines)

    async def read_project_file(project: str, path: str) -> str:
        target = await files.project(project)
        project_file, data = await files.read_bytes(target, path)
        return truncate(decode_text(data, project_file.name), config.MAX_TOOL_READ_CHARS)

    async def write_project_file(
        project: str, path: str, content: str, overwrite: bool = False
    ) -> str:
        target = await files.project(project)
        written = await files.write(target, path, content.encode("utf-8"), overwrite)
        return f"Wrote {target.name}/{path.strip('/')} ({written.size_bytes:,} bytes)"

    async def edit_project_file(
        project: str, path: str, old_string: str, new_string: str, replace_all: bool = False
    ) -> str:
        target = await files.project(project)
        project_file, data = await files.read_bytes(target, path)
        content = decode_text(data, project_file.name)

        count = content.count(old_string)
        if count == 0:
            raise ValueError(f"old_string not found in {path}")
        if count > 1 and not replace_all:
            raise ValueError(
                f"old_string is not unique in {path} ({count} matches). "
                "Pass replace_all=true or make old_string more specific"
            )

        updated = content.replace(old_string, new_string, -1 if replace_all else 1)
        await files.write(target, path, updated.encode("utf-8"), overwrite=True)
        return f"Updated {target.name}/{path.strip('/')}"

    async def create_project_folder(project: str, path: str) -> str:
        target = await files.project(project)
        await files.make_folder(target, path)
        return f"{target.name}/{path.strip('/')}/"

    async def copy_project_path(
        source_project: str, source_path: str, destination_project: str, destination_path: str
    ) -> str:
        source = await files.project(source_project)
        target = await files.project(destination_project)
        count, landed = await files.copy(source, source_path, target, destination_path)
        return f"Copied {count} file(s) from {source.name}/{source_path} to {target.name}/{landed}"

    async def move_project_path(project: str, source_path: str, destination_path: str) -> str:
        target = await files.project(project)
        landed = await files.move(target, source_path, destination_path)
        return f"Moved {target.name}/{source_path} to {target.name}/{landed}"

    async def rename_project_path(project: str, path: str, new_name: str) -> str:
        name = new_name.strip()
        if not name or "/" in name or "\\" in name:
            return "new_name must be a name, not a path. To move it elsewhere, use MoveProjectPath."

        target = await files.project(project)
        parts = [part for part in path.strip("/").split("/") if part]
        if not parts:
            return "Give the path of the file or folder to rename, not the project itself."
        destination = "/".join([*parts[:-1], name])

        # A move onto an existing folder would put this inside it, not rename it.
        # A case-only rename finds the source itself there, which is fine.
        existing = await files.entry(target, destination)
        source = await files.entry(target, path)
        if existing is not None and (source is None or existing.id != source.id):
            return f"{target.name}/{destination} already exists. Pick another name or ask the user."

        landed = await files.move(target, path, destination)
        return f"Renamed {target.name}/{path.strip('/')} to {target.name}/{landed}"

    async def delete_project_path(project: str, path: str) -> str:
        target = await files.project(project)
        removed = await files.delete(target, path)
        return f"Deleted {target.name}/{removed}"

    return {
        ListProjects.__name__: Tool(schema=ListProjects, handler=list_projects),
        CreateProject.__name__: Tool(schema=CreateProject, handler=create_project),
        ListProjectFolder.__name__: Tool(schema=ListProjectFolder, handler=list_project_folder),
        FindProjectFiles.__name__: Tool(schema=FindProjectFiles, handler=find_project_files),
        ReadProjectFile.__name__: Tool(schema=ReadProjectFile, handler=read_project_file),
        WriteProjectFile.__name__: Tool(schema=WriteProjectFile, handler=write_project_file),
        # Creating something is cheap to undo and asks nobody. Changing or removing what
        # already exists asks first -- the line the command-line assistant drew.
        EditProjectFile.__name__: Tool(
            schema=EditProjectFile,
            handler=edit_project_file,
            requires_approval=True,
            describe=lambda project, path, **_: f"edit {project}/{path}",
        ),
        CreateProjectFolder.__name__: Tool(
            schema=CreateProjectFolder, handler=create_project_folder
        ),
        CopyProjectPath.__name__: Tool(schema=CopyProjectPath, handler=copy_project_path),
        MoveProjectPath.__name__: Tool(
            schema=MoveProjectPath,
            handler=move_project_path,
            requires_approval=True,
            describe=lambda project, source_path, destination_path: (
                f"move {project}/{source_path} to {project}/{destination_path}"
            ),
        ),
        RenameProjectPath.__name__: Tool(
            schema=RenameProjectPath,
            handler=rename_project_path,
            requires_approval=True,
            describe=lambda project, path, new_name: f"rename {project}/{path} to {new_name}",
        ),
        DeleteProjectPath.__name__: Tool(
            schema=DeleteProjectPath,
            handler=delete_project_path,
            requires_approval=True,
            # a deletion cannot be undone, so it is asked even in the client's auto mode
            always_ask=True,
            describe=lambda project, path: f"delete {project}/{path}",
        ),
    }

