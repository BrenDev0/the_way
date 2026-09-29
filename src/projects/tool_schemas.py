from pydantic import BaseModel, Field

PROJECT = "Project name, exactly as ListProjects shows it. '.the_way' is your own workspace."
PATH = "Path inside the project, for example 'docs/report.md'. '.' is the project root."


class ListProjects(BaseModel):
    """List the user's projects -- the folders of files they keep on the server and can
    open from the desktop app. Every other project tool takes one of these names."""


class CreateProject(BaseModel):
    """Create a new, empty project for the user."""

    name: str = Field(description="The project name, for example 'Acme website'")


class ListProjectFolder(BaseModel):
    """List one folder of a project: sub-folders (with a trailing /) and files with their
    sizes. Use this to see what is inside a folder before reading anything -- ReadProjectFile
    only works on files, never on folders."""

    project: str = Field(description=PROJECT)
    path: str = Field(default=".", description=PATH)


class FindProjectFiles(BaseModel):
    """Find files and folders anywhere in a project. Every word of the query must appear
    somewhere in the path, so 'progreso report' finds a report.md inside a folder named
    after progreso. Folders come back with a trailing / -- list those with
    ListProjectFolder rather than reading them. Prefer two or three distinctive words over
    a full filename."""

    project: str = Field(description=PROJECT)
    query: str = Field(description="Words to look for in the path, for example 'progreso report'")


class ReadProjectFile(BaseModel):
    """Read the text of one file in a project. Plain text, markdown, code, CSV, JSON,
    PDF and Word files can be read; images and other binaries cannot."""

    project: str = Field(description=PROJECT)
    path: str = Field(description=PATH)


class WriteProjectFile(BaseModel):
    """Write a text file into a project, creating any missing folders on the way.

    Never call this with content you did not read or write in this conversation -- to put
    an existing file somewhere else, use CopyProjectPath or MoveProjectPath, which move the
    bytes and cannot change them."""

    project: str = Field(description=PROJECT)
    path: str = Field(description="Where to write, for example 'reports/q3.md'")
    content: str = Field(description="The complete text of the file")
    overwrite: bool = Field(
        default=False,
        description="If true, replace the file if it already exists; if false (default) an "
        "error is raised",
    )


class EditProjectFile(BaseModel):
    """Change an existing project file by replacing an exact piece of its text."""

    project: str = Field(description=PROJECT)
    path: str = Field(description=PATH)
    old_string: str = Field(
        description="The exact existing text to replace; must match exactly, including whitespace"
    )
    new_string: str = Field(description="The text to replace old_string with")
    replace_all: bool = Field(
        default=False,
        description="If true, replace every occurrence of old_string; if false (default), "
        "old_string must be unique in the file",
    )


class CreateProjectFolder(BaseModel):
    """Create a folder, and any missing parent folders, in a project."""

    project: str = Field(description=PROJECT)
    path: str = Field(description="The folder to create, for example 'reports/2026'")


class CopyProjectPath(BaseModel):
    """Copy a file or a whole folder, within a project or into another one, leaving the
    original in place. Use this to put a copy where the user wants it -- never read a file
    and re-create it at the new path, which round-trips the contents through your context
    where they can be truncated or altered."""

    source_project: str = Field(description=PROJECT)
    source_path: str = Field(description="The existing file or folder to copy")
    destination_project: str = Field(description=PROJECT)
    destination_path: str = Field(
        description="Where to copy to. If it is an existing folder, the source is copied "
        "into it under its own name. Parent folders are created as needed."
    )


class MoveProjectPath(BaseModel):
    """Move or rename a file or folder inside a project. The original no longer exists at
    the old path afterwards. If the user may still want the original, use CopyProjectPath."""

    project: str = Field(description=PROJECT)
    source_path: str = Field(description="The existing file or folder to move")
    destination_path: str = Field(
        description="The new path. If it is an existing folder, the source is moved into "
        "it under its own name. Parent folders are created as needed."
    )


class DeleteProjectPath(BaseModel):
    """Delete a file, or a folder and everything inside it, from a project."""

    project: str = Field(description=PROJECT)
    path: str = Field(description=PATH)
