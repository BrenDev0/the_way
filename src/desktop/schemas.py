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


class RenamePath(BaseModel):
    """Rename a file or directory on the user's computer where it is, keeping it in the
    same folder. Use MovePath to put it somewhere else."""

    path: str = Field(description=f"The existing file or directory. {LOCAL}")
    new_name: str = Field(
        description="The new name only, not a path -- for example 'informe-final.docx'. Keep "
        "the file's extension unless the user asked to change it."
    )


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


# --- git, in the folder the user has open -------------------------------------------
#
# One tool per thing git is asked to do: there is no "run this git command", so there is no
# reset, clean, checkout or force-push to reach. They run the user's own git, with the
# user's own sign-in -- the app never holds a password or token. When git is not installed
# or not set up (no name and email, no remote, no credentials) the tool's error says what
# the user has to do; pass that on in their language rather than trying to work around it.


class GitStatus(BaseModel):
    """Show the state of the git repository in the open folder: the branch, how many
    commits it is ahead of or behind its remote (`[ahead 1, behind 2]`, as of the last
    GitFetch), and every changed, staged or untracked file."""

    ignored: bool = Field(
        default=False,
        description="If true, also list files git ignores (marked '!!') -- how to spot "
        "source-looking files that no commit will ever contain",
    )


class GitLog(BaseModel):
    """List recent commits of the repository in the open folder, newest first, one line
    each: short hash, date, author, subject."""

    limit: int = Field(default=20, description="How many commits to show (at most 100)")
    path: str | None = Field(
        default=None, description=f"Only commits that touched this file or folder. {LOCAL}"
    )


class GitDiff(BaseModel):
    """Show what changed in the working tree of the repository in the open folder --
    unstaged by default. Look at this before staging or committing anything."""

    staged: bool = Field(
        default=False, description="If true, show what is staged for the next commit instead"
    )
    stat: bool = Field(default=False, description="If true, only the per-file summary, not the lines")
    path: str | None = Field(default=None, description=f"Limit to this file or folder. {LOCAL}")


class GitShow(BaseModel):
    """Show one commit -- its message, the files it touched and the changes."""

    revision: str = Field(
        default="HEAD",
        description="A commit hash, branch, tag or HEAD~1 style reference; HEAD is the latest",
    )


class GitFetch(BaseModel):
    """Ask the remote what is new, without changing any file here. Do this before judging
    whether the repository is ahead of or behind it; GitStatus then shows the result."""

    remote: str | None = Field(default=None, description="The remote's name; the default one if omitted")


class GitAdd(BaseModel):
    """Stage files for the next commit. Needs the user's approval. Name the exact paths --
    never '.' to take everything, which commits what nobody looked at. Check with GitStatus
    or GitDiff first, and check again afterwards."""

    paths: list[str] = Field(description=f"The files or folders to stage. {LOCAL}")


class GitCommit(BaseModel):
    """Commit what is staged, with the message you give. Needs the user's approval, which
    shows them the message and the staged files. Stage with GitAdd first; nothing staged
    is an error. Commits are local -- they leave the computer only with GitPush."""

    message: str = Field(description="The commit message: a short subject, in the project's own style")


class GitPush(BaseModel):
    """Send the local commits to the remote. ALWAYS asks the user, even when they have
    approved everything else, and shows which commits will go. Never forced: if the remote
    has commits this computer lacks, the push is refused and nothing is overwritten.

    If it fails because git is not signed in on this computer, the error says so. Tell the
    user they have to set up their own git access once (Git Credential Manager or an SSH
    key); you cannot do it for them and must not ask for their password or token."""

    remote: str | None = Field(default=None, description="The remote's name; the default one if omitted")
    branch: str | None = Field(default=None, description="The branch to push; the current one if omitted")
    set_upstream: bool = Field(
        default=False,
        description="If true, remember this remote branch as the one this branch follows -- "
        "needed the first time a branch is pushed",
    )


# --- a command on the user's computer ----------------------------------------------------


class RunCommand(BaseModel):
    """Run ONE command in the user's own shell, on their computer, in the folder they have open.
    For skills and requests that need a command no other tool does (`node`, `curl`, `npm`...).

    The user is asked EVERY time, even when they have approved everything else, and sees the
    exact command: so run one small command per call, say before it what it is for, and never
    chain steps the user has not seen. Prefer the file tools for files and the Git tools for
    git; they are safer and need no shell.

    The result begins with the shell it ran in -- PowerShell on Windows, bash on Mac -- so write
    commands for that one. It runs with the user's own permissions and is NOT fenced to the
    folder: never delete or change anything outside it, install software, or send data anywhere,
    unless the user asked for that in plain words. Never put a password or token in a command.
    A command that needs input will not get any; one that runs too long is ended."""

    command: str = Field(description="The command, exactly as the user's shell should run it")
    timeout_seconds: int = Field(
        default=60,
        description="How long it may run before it is ended, up to 600 (ten minutes)",
    )
