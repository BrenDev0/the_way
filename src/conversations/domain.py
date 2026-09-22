from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from src.core.llm.domain import TokenUsage, ToolCall
from src.core.tools.domain import ToolResult


class ConversationStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    FAILED = "failed"


@dataclass(frozen=True)
class TurnState:
    status: ConversationStatus = ConversationStatus.IDLE
    pending_tool_calls: tuple[ToolCall, ...] = ()
    completed_tool_results: tuple[ToolResult, ...] = ()
    iterations_used: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass
class Conversation:
    id: UUID
    organization_id: UUID
    user_id: UUID
    title: str
    turn: TurnState
    created_at: datetime
    updated_at: datetime


@dataclass
class ConversationCreate:
    organization_id: UUID
    user_id: UUID
    title: str
