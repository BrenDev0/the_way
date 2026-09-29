"""Tools the desktop app carries out on the user's own machine.

The server offers these schemas to the model and never runs them: a call pauses the turn,
the desktop app runs it and posts back what it returned (see docs/desktop-tools.md for
the contract). Every local path is relative to the folder the user has open in the
desktop app, which the app is responsible for sandboxing -- nothing may resolve outside it.
"""

from pydantic import BaseModel, Field

LOCAL = "Relative to the folder the user has open in the desktop app; never absolute"


# --- local files ---------------------------------------------------------------------


class CreateDir(BaseModel):
    """Create a new directory (and missing parent directories) on the user's computer."""

    dir_path: str = Field(description=f"The directory to create. {LOCAL}")


class CreateFile(BaseModel):
    """Create a new file on the user's computer, optionally with initial text content."""

    file_path: str = Field(description=f"The file to create. {LOCAL}")
    content: str = Field(default="", description="Optional initial content")
    overwrite: bool = Field(
        default=False,
        description="If true, overwrite the file if it already exists; if false (default) "
        "an error is raised",
    )


class ReadFile(BaseModel):
    """Get the contents of a file on the user's computer."""

    file_path: str = Field(description=f"The file to read. {LOCAL}")


class UpdateFile(BaseModel):
    """Update an existing file on the user's computer by replacing an exact substring."""

    file_path: str = Field(description=f"The file to update. {LOCAL}")
    old_string: str = Field(
        description="The exact existing text to replace; must match exactly, including whitespace"
    )
    new_string: str = Field(description="The text to replace old_string with")
    replace_all: bool = Field(
        default=False,
        description="If true, replace every occurrence of old_string; if false (default), "
        "old_string must be unique in the file",
    )


class ListDir(BaseModel):
    """List a directory on the user's computer: sub-directories (with a trailing /) and
    files with their sizes. Use this to see what is inside a folder before reading
    anything -- ReadFile only works on files, never on directories."""

    dir_path: str = Field(default=".", description=f"Directory to list. {LOCAL}")


class SearchFile(BaseModel):
    """Find files and folders on the user's computer by name. Every word of the query must
    appear somewhere in the path. Folders come back with a trailing / -- list those with
    ListDir rather than reading them. Build directories (.venv, node_modules,
    __pycache__, .git) are skipped."""

    file_name: str = Field(description="Words to look for in the path, for example 'progreso report'")
    base_dir: str = Field(default=".", description=f"Directory to search under. {LOCAL}")


class SearchCode(BaseModel):
    """Find which files on the user's computer CONTAIN a piece of text, and on which lines.
    This is the tool for 'where is this used' and 'what would this rename touch' --
    SearchFile only matches names. Never read files one by one looking for something;
    search for it here first, then read the hits.

    Results come back as 'path:line: text'. The count at the end is the real total even
    when the listing is cut short, so trust it over the number of lines shown."""

    pattern: str = Field(
        description="Regular expression to look for. Plain words work as-is; escape "
        ". * + ? [ ] ( ) | \\ to match them literally"
    )
    base_dir: str = Field(default=".", description=f"Directory or file to search. {LOCAL}")
    file_glob: str | None = Field(
        default=None, description="Only search files whose name matches this glob, e.g. '*.py'"
    )
    case_sensitive: bool = Field(default=False, description="If true, match case exactly")
    files_only: bool = Field(
        default=False,
        description="If true, return just the matching paths with a count each",
    )


class CopyPath(BaseModel):
    """Copy a file or directory on the user's computer, leaving the original in place.
    NEVER read a file and re-create it at the new path -- copying moves the bytes on disk
    and cannot corrupt them."""

    source: str = Field(description=f"The existing file or directory. {LOCAL}")
    destination: str = Field(
        description="Where to copy to. If source is a file and destination is an existing "
        "directory, the file is copied into it under the same name."
    )
    overwrite: bool = Field(default=False, description="If true, replace anything already there")


class MovePath(BaseModel):
    """Move or rename a file or directory on the user's computer. The original no longer
    exists at the old path afterwards."""

    source: str = Field(description=f"The existing file or directory. {LOCAL}")
    destination: str = Field(description="The new path")
    overwrite: bool = Field(default=False, description="If true, replace anything already there")


class DeleteFile(BaseModel):
    """Delete a file on the user's computer."""

    file_path: str = Field(description=f"The file to delete. {LOCAL}")


class DeleteDir(BaseModel):
    """Delete a directory on the user's computer."""

    dir_path: str = Field(description=f"The directory to delete. {LOCAL}")
    recursive: bool = Field(
        default=False,
        description="If true, delete it and all its contents; if false, it must be empty",
    )


# --- moving files between the computer and the user's projects ----------------------


class UploadToProject(BaseModel):
    """Upload a file or a whole folder from the user's computer into one of their projects,
    so it is kept on the server and reachable from anywhere. Build directories (.venv,
    node_modules, .git) are skipped."""

    local_path: str = Field(description=f"The file or folder to upload. {LOCAL}")
    project: str = Field(description="Project name, exactly as ListProjects shows it")
    destination_path: str = Field(
        default=".", description="Folder inside the project to upload into; '.' is its root"
    )


class DownloadFromProject(BaseModel):
    """Download a file or folder from one of the user's projects onto their computer."""

    project: str = Field(description="Project name, exactly as ListProjects shows it")
    path: str = Field(description="The file or folder inside the project")
    local_path: str = Field(default=".", description=f"Where to put it. {LOCAL}")
    overwrite: bool = Field(
        default=False,
        description="If true, replace local files that are in the way; if false (default) "
        "an error is raised rather than overwriting the user's copy",
    )


# --- the user's own browser ------------------------------------------------------------


class OpenBrowserPage(BaseModel):
    """Open a URL in the user's own browser window and return the page's visible text.

    The window keeps its signed-in sessions between runs, so anything the user is logged
    into stays logged in. Use this when a task needs a site the user is authenticated on
    -- WebSearch and ExtractWebPages are better for public pages."""

    url: str = Field(description="Full URL including scheme, for example 'https://web.whatsapp.com'")


class ReadBrowserPage(BaseModel):
    """Re-read the visible text of the page already open in the browser. Use after
    clicking or typing to see what changed, rather than opening the URL again."""


class ClickBrowserElement(BaseModel):
    """Click the first button or link whose visible text contains what you give.
    Needs the user's approval."""

    text: str = Field(description="Visible text on the button or link, for example 'Continue'")


class TypeInBrowser(BaseModel):
    """Type into whichever field on the page currently has focus. Needs the user's
    approval. Click the field first if it is not already focused."""

    text: str = Field(description="The text to type")
    then_enter: bool = Field(default=False, description="Press enter afterwards")


class ListBrowserTabs(BaseModel):
    """List every tab open in the browser, with its title and URL. Check this before
    opening a page the user is likely to already have open and signed into."""


class SwitchBrowserTab(BaseModel):
    """Switch to the first open tab whose title or URL contains what you give, and read it."""

    match: str = Field(description="Part of the tab's title or URL, for example 'whatsapp'")


class CloseBrowser(BaseModel):
    """Close the browser window. The signed-in sessions are kept for next time."""


class FindWhatsappChat(BaseModel):
    """Look up who a name matches in the user's WhatsApp before sending anything.

    Call this first whenever the user names a person rather than giving a number. When it
    resolves to a single chat, go straight on and send -- the user approves the send
    itself, with the chat name and the full message in front of them. Ask only when it
    genuinely comes back with several."""

    name: str = Field(description="The person as the user referred to them, for example 'John Doe'")


class ReadWhatsappChat(BaseModel):
    """Open a WhatsApp conversation and read its recent messages, each marked with who
    sent it."""

    name: str = Field(description="The chat name, ideally exactly as FindWhatsappChat returned it")
    limit: int = Field(default=15, description="How many of the most recent messages to return")


class SendWhatsappMessage(BaseModel):
    """Send one WhatsApp message to one person through WhatsApp Web.

    Needs the user's approval. This is the WhatsApp account signed into the browser, a
    different sender from the CRM's WhatsApp channel: CX sends over the WhatsApp Business
    API, which only allows a free-form message within 24 hours of the contact's last
    message. This tool has no such limit, but the message arrives from the browser's
    number, not the CRM's -- say which you are using if there is any doubt.

    `to` is either a phone number, or a chat name exactly as FindWhatsappChat returned it
    -- never guess a name. Send one message per call, so every message is approved on its
    own and a mistake stops at one."""

    to: str = Field(
        description="A phone number in full international form ('521234567890'), or an "
        "exact chat name from FindWhatsappChat"
    )
    message: str = Field(description="The message text, exactly as it should be sent")
