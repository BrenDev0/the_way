from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from src.core.schemas import ApiBaseModel
from src.core.tools.domain import ToolLocation

from .domain import ConversationClient, ConversationStatus


class CreateConversationRequest(ApiBaseModel):
    title: str = "New conversation"
    client: ConversationClient = ConversationClient.DESKTOP


class SendMessageRequest(ApiBaseModel):
    message: str
    # The client will speak the reply aloud, so it should be written to be heard.
    voice: bool = False
    # The folder open in the desktop app right now -- the one its local file tools work
    # in -- or none. Sent with every message, since the user can change it at any time.
    local_folder: str | None = Field(default=None, max_length=1024)
    # Or: the user works in one of their projects on the server -- "project/folder". Then
    # that is where things are read, written and delivered by default.
    remote_folder: str | None = Field(default=None, max_length=1024)


class PendingToolCallResponse(ApiBaseModel):
    id: str
    name: str
    args: dict[str, Any]
    # 'desktop': the client runs it and posts the output. 'server': the client only
    # approves or rejects it, and the server runs it.
    location: ToolLocation
    requires_approval: bool
    detail: str | None = Field(default=None, min_length=0)
    # Arguments the approver may pick, and the values allowed for each.
    choices: dict[str, list[str]] = Field(default_factory=dict)
    # A fuller description for the approval dialog, when the tool has one.
    preview: str | None = Field(default=None, min_length=0)
    # Ask the user even in the client's auto mode: it spends their money (an image).
    always_ask: bool = False


class ConversationResponse(ApiBaseModel):
    id: UUID
    title: str
    client: ConversationClient
    status: ConversationStatus
    pending_tool_calls: list[PendingToolCallResponse]
    iterations_used: int
    total_tokens: int
    created_at: datetime
    updated_at: datetime


class ToolResolutionRequest(ApiBaseModel):
    tool_call_id: str = Field(min_length=1)
    approved: bool
    # Why it was refused, or what to do instead; the model is told to follow it.
    feedback: str = Field(default="", min_length=0)
    # What a desktop tool returned. Required when approving a desktop call, refused for a
    # server one. Empty output is a real answer (an empty file, a quiet command).
    output: str | None = Field(default=None, min_length=0)
    failed: bool = False
    # The approver's picks among the call's choices, e.g. {"model": "gpt-image-2.5-sunburst"}.
    # Anything the tool does not offer as a choice is ignored.
    args: dict[str, str] = Field(default_factory=dict)


class ResolveToolCallsRequest(ApiBaseModel):
    resolutions: list[ToolResolutionRequest]
    # Sent again on resume: voice is the client's state, never stored with the turn.
    voice: bool = False
    local_folder: str | None = Field(default=None, max_length=1024)
    remote_folder: str | None = Field(default=None, max_length=1024)


class MessageResponse(ApiBaseModel):
    role: str
    content: Any
    tool_calls: list[Any] | None = None
    tool_call_id: str | None = None


class DeleteConversationResponse(ApiBaseModel):
    detail: str
