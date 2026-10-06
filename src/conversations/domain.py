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
    # The turn stopped on something that passes or that the user can fix -- the model's
    # rate limit or quota, a timeout, the worker going down. Everything done so far is
    # stored; POST .../resume carries on from where it stopped.
    PAUSED = "paused"
    FAILED = "failed"


class PauseReason(StrEnum):
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    CREDENTIALS = "credentials"
    # the worker stopped mid-turn: restarted, redeployed, crashed
    INTERRUPTED = "interrupted"


class ConversationClient(StrEnum):
    # Offered the desktop tools: files on the user's computer, their browser, uploads.
    DESKTOP = "desktop"
    # A browser client cannot reach the user's machine, so it gets server tools only.
    WEB = "web"


@dataclass(frozen=True)
class TurnPause:
    reason: PauseReason
    # what the provider said, for the user to act on (a quota, a key)
    detail: str = ""
    paused_at: datetime | None = None
    # the earliest a retry is worth trying, when the provider said
    retry_after: datetime | None = None


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
    # why the turn is PAUSED; None in any other status
    pause: TurnPause | None = None


@dataclass(frozen=True)
class ToolResolution:
    """How the client settled one pending call: approved or rejected, and for a desktop
    tool, what running it produced."""

    tool_call_id: str
    approved: bool
    feedback: str = ""
    output: str | None = None
    failed: bool = False
    # The approver's picks among the tool's choices -- the image model, say.
    args: dict[str, str] = field(default_factory=dict)


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


@dataclass(frozen=True)
class TurnContext:
    """What a turn is told besides the conversation, split by how often it changes --
    which decides where it goes, since a provider caches the prompt only up to the first
    byte that differs from the last request."""

    # Ahead of the history: the CX workflow, the knowledge index. Rarely changes.
    stable: tuple[str, ...] = ()
    # After the history: the date, the working folder, voice, preferences.
    current: str = ""


@dataclass
class ConversationCreate:
    organization_id: UUID
    user_id: UUID
    title: str
    client: ConversationClient = ConversationClient.DESKTOP
