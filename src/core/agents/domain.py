from dataclasses import dataclass, field, replace
from enum import StrEnum

from src.core.llm.domain import Message, TokenUsage, ToolCall
from src.core.tools.domain import ToolResult

DEFAULT_MAX_ITERATIONS = 40
DEFAULT_MAX_CONVERSATION_CHARS = 400_000


class LoopStatus(StrEnum):
    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"
    ITERATION_LIMIT = "iteration_limit"
    CONVERSATION_LIMIT = "conversation_limit"


@dataclass(frozen=True)
class LoopState:
    messages: list[Message] = field(default_factory=list)
    pending_tool_calls: tuple[ToolCall, ...] = ()
    completed_tool_results: tuple[ToolResult, ...] = ()
    iterations_used: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)

    def advanced(self, **changes) -> "LoopState":
        return replace(self, **changes)


@dataclass(frozen=True)
class LoopResult:
    status: LoopStatus
    state: LoopState
    text: str = ""

    @property
    def is_suspended(self) -> bool:
        return self.status is LoopStatus.AWAITING_APPROVAL
