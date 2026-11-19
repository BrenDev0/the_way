from pydantic import BaseModel

from src.core.tools.domain import Tool, ToolLocation

from .schemas import (
    ClickBrowserElement,
    CloseBrowser,
    CopyPath,
    CreateDir,
    CreateFile,
    DeleteDir,
    DeleteFile,
    DownloadFromProject,
    FindWhatsappChat,
    GitAdd,
    GitCommit,
    GitDiff,
    GitFetch,
    GitLog,
    GitPush,
    GitShow,
    GitStatus,
    ListBrowserTabs,
    ListComputerFolder,
    ListDir,
    MovePath,
    OpenBrowserPage,
    ReadBrowserPage,
    ReadComputerFile,
    ReadFile,
    ReadWhatsappChat,
    RenamePath,
    RequestComputerAccess,
    RunCommand,
    SearchCode,
    SearchComputer,
    SearchComputerText,
    SearchFile,
    SendWhatsappMessage,
    SwitchBrowserTab,
    TypeInBrowser,
    UpdateFile,
    UploadToProject,
)

FILES: tuple[type[BaseModel], ...] = (
    ReadFile,
    ListDir,
    SearchFile,
    SearchCode,
    CreateDir,
    CreateFile,
    UpdateFile,
    CopyPath,
    MovePath,
    RenamePath,
    DeleteFile,
    DeleteDir,
)

TRANSFER: tuple[type[BaseModel], ...] = (UploadToProject, DownloadFromProject)

BROWSER: tuple[type[BaseModel], ...] = (
    OpenBrowserPage,
    ReadBrowserPage,
    ClickBrowserElement,
    TypeInBrowser,
    ListBrowserTabs,
    SwitchBrowserTab,
    CloseBrowser,
    FindWhatsappChat,
    ReadWhatsappChat,
    SendWhatsappMessage,
)

SHELL: tuple[type[BaseModel], ...] = (RunCommand,)

COMPUTER: tuple[type[BaseModel], ...] = (
    RequestComputerAccess,
    ListComputerFolder,
    SearchComputer,
    SearchComputerText,
    ReadComputerFile,
)

GIT: tuple[type[BaseModel], ...] = (
    GitStatus,
    GitLog,
    GitDiff,
    GitShow,
    GitFetch,
    GitAdd,
    GitCommit,
    GitPush,
)

# Creating something new is cheap to undo and asks nobody. Changing or removing what
# already exists asks first; so does anything that reaches outside the machine -- a click,
# a keystroke or a sent message lands somewhere the user cannot take it back from -- and
# anything that carries files across it, which can overwrite either side. The desktop
# app shows the approval; the flag tells it which calls need one.
REQUIRES_APPROVAL: frozenset[type[BaseModel]] = frozenset(
    {
        UpdateFile,
        MovePath,
        RenamePath,
        DeleteFile,
        DeleteDir,
        UploadToProject,
        DownloadFromProject,
        ClickBrowserElement,
        TypeInBrowser,
        SendWhatsappMessage,
        GitAdd,
        GitCommit,
        GitPush,
        RunCommand,
        RequestComputerAccess,
    }
)

SCHEMAS: tuple[type[BaseModel], ...] = FILES + TRANSFER + BROWSER + GIT + SHELL + COMPUTER

# Asked even when the user has the app approve everything else on its own (auto mode):
# a deletion cannot be undone, a push leaves the machine for good, and a command can do
# anything the user's account can.
# Opening a folder to the agent is the user's decision every time, auto mode or not.
ALWAYS_ASK: frozenset[type[BaseModel]] = frozenset(
    {DeleteFile, DeleteDir, GitPush, RunCommand, RequestComputerAccess}
)


def build() -> dict[str, Tool]:
    return {
        schema.__name__: Tool(
            schema=schema,
            location=ToolLocation.DESKTOP,
            requires_approval=schema in REQUIRES_APPROVAL,
            always_ask=schema in ALWAYS_ASK,
        )
        for schema in SCHEMAS
    }
