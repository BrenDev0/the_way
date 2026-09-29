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


class PendingToolCallResponse(ApiBaseModel):
    id: str
    name: str
    args: dict[str, Any]
    # 'desktop': the client runs it and posts the output. 'server': the client only
    # approves or rejects it, and the server runs it.
    location: ToolLocation
    requires_approval: bool
    detail: str | None = Field(default=None, min_length=0)


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


class ResolveToolCallsRequest(ApiBaseModel):
    resolutions: list[ToolResolutionRequest]


class MessageResponse(ApiBaseModel):
    role: str
    content: Any
    tool_calls: list[Any] | None = None
    tool_call_id: str | None = None


class DeleteConversationResponse(ApiBaseModel):
    detail: str
