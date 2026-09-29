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
    ListBrowserTabs,
    ListDir,
    MovePath,
    OpenBrowserPage,
    ReadBrowserPage,
    ReadFile,
    ReadWhatsappChat,
    SearchCode,
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

# Creating something new is cheap to undo and asks nobody. Changing or removing what
# already exists asks first; so does anything that reaches outside the machine -- a click,
# a keystroke or a sent message lands somewhere the user cannot take it back from -- and
# anything that carries files across it, which can overwrite either side. The desktop
# app shows the approval; the flag tells it which calls need one.
REQUIRES_APPROVAL: frozenset[type[BaseModel]] = frozenset(
    {
        UpdateFile,
        MovePath,
        DeleteFile,
        DeleteDir,
        UploadToProject,
        DownloadFromProject,
        ClickBrowserElement,
        TypeInBrowser,
        SendWhatsappMessage,
    }
)

SCHEMAS: tuple[type[BaseModel], ...] = FILES + TRANSFER + BROWSER


def build() -> dict[str, Tool]:
    return {
        schema.__name__: Tool(
            schema=schema,
            location=ToolLocation.DESKTOP,
            requires_approval=schema in REQUIRES_APPROVAL,
        )
        for schema in SCHEMAS
    }
