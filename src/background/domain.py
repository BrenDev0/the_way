from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class TaskStatus(StrEnum):
    RUNNING = "running"
    # Stopped on a call only the user can approve; its run is saved and carries on once
    # they answer (paused.py). Fits the 16-character status column.
    NEEDS_APPROVAL = "needs_approval"
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
