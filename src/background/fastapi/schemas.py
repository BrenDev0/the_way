from collections.abc import Sequence
from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import Field

from src.conversations.fastapi.schemas import (
    PendingToolCallResponse,
    ToolResolutionRequest,
)
from src.core.tools.domain import ClientRequest
from src.fastapi.schemas import ApiBaseModel

from ..domain import BackgroundTask, TaskStatus


class BackgroundTaskResponse(ApiBaseModel):
    id: UUID
    conversation_id: UUID | None
    # Written by the model, not typed into a form: "." is the project's root, and a short
    # value is still a real one, so the input minimum does not apply.
    description: str = Field(min_length=0)
    status: TaskStatus
    result: str | None = Field(default=None, min_length=0)
    deliver_project: str | None = Field(min_length=0)
    deliver_path: str | None = Field(min_length=0)
    created_at: datetime
    updated_at: datetime
    # While status is needs_approval: the calls the task is waiting on the user for.
    pending_approval: list[PendingToolCallResponse] = Field(default_factory=list)

    @classmethod
    def from_domain(
        cls, task: BackgroundTask, pending_approval: Sequence[ClientRequest] = ()
    ) -> Self:
        return cls(
            id=task.id,
            conversation_id=task.conversation_id,
            description=task.description,
            status=task.status,
            result=task.result,
            deliver_project=task.deliver_project,
            deliver_path=task.deliver_path,
            created_at=task.created_at,
            updated_at=task.updated_at,
            pending_approval=[PendingToolCallResponse.from_domain(r) for r in pending_approval],
        )


class ApproveTaskRequest(ApiBaseModel):
    """The user's answer to every call the task is waiting on. Same shape as a turn's
    tool results; `output` does not apply, since the server runs these calls itself."""

    resolutions: list[ToolResolutionRequest]
