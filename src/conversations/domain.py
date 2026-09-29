from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from src.core.llm.domain import TokenUsage, ToolCall
from src.core.tools.domain import ClientRequest, Decision, ToolResult


class ConversationStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    # The turn is paused on tool calls only the client can settle: desktop tools to run,
    # or server tools the user has to approve. It resumes once every one is resolved.
    AWAITING_CLIENT = "awaiting_client"
    FAILED = "failed"


class ConversationClient(StrEnum):
    # Offered the desktop tools: files on the user's computer, their browser, uploads.
    DESKTOP = "desktop"
    # A browser client cannot reach the user's machine, so it gets server tools only.
    WEB = "web"


@dataclass(frozen=True)
class TurnState:
    status: ConversationStatus = ConversationStatus.IDLE
    pending_tool_calls: tuple[ToolCall, ...] = ()
    completed_tool_results: tuple[ToolResult, ...] = ()
    iterations_used: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)
    pending_requests: tuple[ClientRequest, ...] = ()
    # The client's answers to the pending calls, held until the worker resumes the turn.
    decisions: dict[str, Decision] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResolution:
    """How the client settled one pending call: approved or rejected, and for a desktop
    tool, what running it produced."""

    tool_call_id: str
    approved: bool
    feedback: str = ""
    output: str | None = None
    failed: bool = False


@dataclass
class Conversation:
    id: UUID
    organization_id: UUID
    user_id: UUID
    title: str
    turn: TurnState
    created_at: datetime
    updated_at: datetime
    client: ConversationClient = ConversationClient.DESKTOP


@dataclass
class ConversationCreate:
    organization_id: UUID
    user_id: UUID
    title: str
    client: ConversationClient = ConversationClient.DESKTOP
