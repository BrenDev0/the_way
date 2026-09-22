from datetime import datetime
from typing import Any
from uuid import UUID

from src.core.schemas import ApiBaseModel

from .domain import ConversationStatus


class CreateConversationRequest(ApiBaseModel):
    title: str = "New conversation"


class SendMessageRequest(ApiBaseModel):
    message: str


class ConversationResponse(ApiBaseModel):
    id: UUID
    title: str
    status: ConversationStatus
    iterations_used: int
    total_tokens: int
    created_at: datetime
    updated_at: datetime


class MessageResponse(ApiBaseModel):
    role: str
    content: Any
    tool_calls: list[Any] | None = None
    tool_call_id: str | None = None


class DeleteConversationResponse(ApiBaseModel):
    detail: str
