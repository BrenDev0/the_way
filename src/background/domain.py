from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class TaskStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class BackgroundTask:
    id: UUID
    organization_id: UUID
    user_id: UUID
    conversation_id: UUID | None
    description: str
    instructions: str
    folder: str
    deliver_project: str | None
    deliver_path: str | None
    status: TaskStatus
    result: str | None
    reported: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class BackgroundTaskCreate:
    organization_id: UUID
    user_id: UUID
    conversation_id: UUID | None
    description: str
    instructions: str
    deliver_project: str | None = None
    deliver_path: str | None = None
