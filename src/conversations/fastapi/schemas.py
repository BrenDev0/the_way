from datetime import datetime
from typing import Any, Self
from uuid import UUID

from pydantic import Field

from src.core.llm.domain import Message
from src.core.tools.domain import ClientRequest, ToolLocation
from src.fastapi.schemas import ApiBaseModel

from ..domain import (
    Conversation,
    ConversationClient,
    ConversationStatus,
    PauseReason,
    ToolResolution,
    TurnPause,
)


class CreateConversationRequest(ApiBaseModel):
    title: str = "New conversation"
    client: ConversationClient = ConversationClient.DESKTOP


class SendMessageRequest(ApiBaseModel):
    # may be empty when files are attached: "here" with a picture says enough
    message: str = Field(default="", min_length=0)
    # Files attached to this message: ids from POST /conversations/attachments, uploaded
    # and completed. Each must be in one of the user's own projects.
    attachments: list[UUID] = Field(default_factory=list, max_length=10)
    # The client will speak the reply aloud, so it should be written to be heard.
    voice: bool = False
    # The folder open in the desktop app right now -- the one its local file tools work
    # in -- or none. Sent with every message, since the user can change it at any time.
    local_folder: str | None = Field(default=None, min_length=0, max_length=1024)
    # Or: the user works in one of their projects on the server -- "project/folder". Then
    # that is where things are read, written and delivered by default.
    remote_folder: str | None = Field(default=None, min_length=0, max_length=1024)


class AttachmentUploadRequest(ApiBaseModel):
    name: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0)


class AttachmentUploadResponse(ApiBaseModel):
    """Where to PUT the file's bytes -- with the same Content-Type -- before completing it
    at POST /projects/{projectId}/files/{fileId}/complete. Then send its fileId with the
    message."""

    file_id: UUID
    project_id: UUID
    project: str
    # where it was put; a name already taken is numbered, so it may differ from the asked one
    path: str
    upload_url: str


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

    @classmethod
    def from_domain(cls, request: ClientRequest) -> Self:
        return cls(
            id=request.call.id,
            name=request.call.name,
            args=request.call.args,
            location=request.location,
            requires_approval=request.requires_approval,
            detail=request.detail,
            choices={name: list(values) for name, values in request.choices.items()},
            preview=request.preview if isinstance(request.preview, str) else None,
            always_ask=request.always_ask,
        )


class PauseResponse(ApiBaseModel):
    # rate_limit, quota, timeout, provider_error, credentials, interrupted
    reason: PauseReason
    # what the provider said, if anything -- worth showing for quota and credentials;
    # "" when it said nothing (an interrupted turn), which the base model would refuse
    detail: str = Field(default="", min_length=0)
    paused_at: datetime | None = None
    # retrying before this is likely to pause again; None when the provider did not say
    retry_after: datetime | None = None

    @classmethod
    def from_domain(cls, pause: TurnPause) -> Self:
        return cls(
            reason=pause.reason,
            detail=pause.detail,
            paused_at=pause.paused_at,
            retry_after=pause.retry_after,
        )


class ConversationResponse(ApiBaseModel):
    id: UUID
    title: str
    client: ConversationClient
    status: ConversationStatus
    # why the turn stopped, while status is 'paused'
    pause: PauseResponse | None = None
    pending_tool_calls: list[PendingToolCallResponse]
    iterations_used: int
    total_tokens: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, conversation: Conversation) -> Self:
        pause = conversation.turn.pause
        return cls(
            id=conversation.id,
            title=conversation.title,
            client=conversation.client,
            status=conversation.turn.status,
            pause=PauseResponse.from_domain(pause) if pause is not None else None,
            pending_tool_calls=[
                PendingToolCallResponse.from_domain(request)
                for request in conversation.turn.pending_requests
            ],
            iterations_used=conversation.turn.iterations_used,
            total_tokens=conversation.turn.usage.total_tokens,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )


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

    def to_domain(self) -> ToolResolution:
        return ToolResolution(
            tool_call_id=self.tool_call_id,
            approved=self.approved,
            feedback=self.feedback,
            output=self.output,
            failed=self.failed,
            args=dict(self.args),
        )


class ResolveToolCallsRequest(ApiBaseModel):
    resolutions: list[ToolResolutionRequest]
    # Sent again on resume: voice is the client's state, never stored with the turn.
    voice: bool = False
    local_folder: str | None = Field(default=None, min_length=0, max_length=1024)
    remote_folder: str | None = Field(default=None, min_length=0, max_length=1024)


class ResumeTurnRequest(ApiBaseModel):
    # The client's state, sent again as on any resume -- never stored with the turn.
    voice: bool = False
    local_folder: str | None = Field(default=None, min_length=0, max_length=1024)
    remote_folder: str | None = Field(default=None, min_length=0, max_length=1024)


class MessageResponse(ApiBaseModel):
    role: str
    content: Any
    tool_calls: list[Any] | None = None
    tool_call_id: str | None = None

    @classmethod
    def from_domain(cls, message: Message) -> Self:
        return cls(
            role=message["role"],
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls"),
            tool_call_id=message.get("tool_call_id"),
        )


class DeleteConversationResponse(ApiBaseModel):
    detail: str
