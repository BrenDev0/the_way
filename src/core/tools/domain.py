from collections.abc import Callable
from dataclasses import dataclass
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

TRUNCATED = "\n[truncated: {omitted} more characters. Narrow the request if you need the rest.]"

MAX_ERROR_CHARS = 500


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + TRUNCATED.format(omitted=len(text) - limit)


@dataclass(frozen=True)
class Tool:
    schema: type[BaseModel]
    handler: Callable[..., Any]
    requires_approval: bool = False
    preview: Callable[..., Any] | None = None
    describe: Callable[..., str] | None = None

    @property
    def name(self) -> str:
        return self.schema.__name__


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    content: str
    failed: bool = False


@dataclass(frozen=True)
class Decision:
    approved: bool
    feedback: str = ""

    def rejection_text(self) -> str:
        return REDIRECTED.format(feedback=self.feedback) if self.feedback else DENIED


@dataclass(frozen=True)
class ApprovalRequest:
    call: ToolCall
    preview: Any | None = None
    detail: str | None = None


class ApprovalRequired(Exception):
    def __init__(self, requests: tuple[ApprovalRequest, ...]) -> None:
        super().__init__(f"{len(requests)} tool call(s) awaiting approval")
        self.requests = requests
