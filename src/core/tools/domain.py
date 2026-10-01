from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from src.core.llm.domain import ToolCall

DENIED = (
    "The user denied this tool call. Do not retry it. Tell them what you were about to "
    "do and ask how they would like to proceed."
)

REDIRECTED = (
    "The user denied this tool call and gave this instruction instead: {feedback}\n"
    "Do not retry the original call. Follow their instruction."
)

UNKNOWN_TOOL = "No tool named {name} is available to you. Do not call it again."

NO_DESKTOP = (
    "{name} runs on the user's desktop, and there is no desktop connected to this run. "
    "Do not call it again; do the work with the tools you have, or say what you could "
    "not do."
)

TRUNCATED = "\n[truncated: {omitted} more characters. Narrow the request if you need the rest.]"

MAX_ERROR_CHARS = 500


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + TRUNCATED.format(omitted=len(text) - limit)


class ToolLocation(StrEnum):
    SERVER = "server"
    # The schema is offered to the model, but the call is carried out by the desktop app,
    # which posts the output back. The server never has a handler for it.
    DESKTOP = "desktop"


@dataclass(frozen=True)
class Tool:
    schema: type[BaseModel]
    handler: Callable[..., Any] | None = None
    requires_approval: bool = False
    preview: Callable[..., Any] | None = None
    describe: Callable[..., str] | None = None
    location: ToolLocation = ToolLocation.SERVER
    # Asks the user even where nobody is watching: a background worker suspends on it
    # instead of approving it itself. For calls that spend the user's money.
    always_ask: bool = False
    # Arguments the person approving may set themselves, and the values allowed for each --
    # which model draws an image, say. Their pick replaces what the model asked for.
    choices: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.schema.__name__

    @property
    def needs_client(self) -> bool:
        return self.requires_approval or self.location is ToolLocation.DESKTOP


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    content: str
    failed: bool = False


@dataclass(frozen=True)
class Decision:
    approved: bool
    feedback: str = ""
    # What a desktop tool produced. Present only when the client ran the call itself.
    output: str | None = None
    failed: bool = False
    # What the approver picked among the tool's choices.
    args: Mapping[str, str] = field(default_factory=dict)

    def rejection_text(self) -> str:
        return REDIRECTED.format(feedback=self.feedback) if self.feedback else DENIED


@dataclass(frozen=True)
class ClientRequest:
    call: ToolCall
    location: ToolLocation = ToolLocation.SERVER
    requires_approval: bool = False
    preview: Any | None = None
    detail: str | None = None
    choices: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Put to the user even when they let everything else through on its own (auto mode).
    always_ask: bool = False


def chosen_args(tool: Tool, call: ToolCall, decision: Decision | None) -> dict[str, Any]:
    """The call's arguments with the approver's picks applied -- only for arguments the
    tool offers as choices, and only values it allows, so an approval cannot smuggle in
    anything else."""
    args = dict(call.args)
    for name, value in (decision.args if decision else {}).items():
        if value in tool.choices.get(name, ()):
            args[name] = value
    return args


class ClientActionRequired(Exception):
    def __init__(self, requests: tuple[ClientRequest, ...]) -> None:
        super().__init__(f"{len(requests)} tool call(s) awaiting the client")
        self.requests = requests
