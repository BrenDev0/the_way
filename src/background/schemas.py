from datetime import datetime
from uuid import UUID

from pydantic import Field

from src.core.schemas import ApiBaseModel

from .domain import TaskStatus


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
