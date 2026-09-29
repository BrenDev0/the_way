from datetime import datetime
from uuid import UUID

from pydantic import Field

from src.core.schemas import ApiBaseModel

from .domain import TaskStatus


class BackgroundTaskResponse(ApiBaseModel):
    id: UUID
    conversation_id: UUID | None
    description: str
    status: TaskStatus
    result: str | None = Field(default=None, min_length=0)
    deliver_project: str | None
    deliver_path: str | None
    created_at: datetime
    updated_at: datetime
